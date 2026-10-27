"""Números dos relatórios (docs/14 §14.7): horas por pessoa, por cliente e por dia, e horas extras.

Tudo é calculado na hora, a partir das tarefas (`ticket_comments`) e dos chamados. Quem vê o quê:
admin e auditor (`report.view_all`) veem tudo; o supervisor, os chamados dos grupos que
supervisiona e o próprio trabalho; os demais, só o próprio trabalho. Em cima disso vale sempre o
filtro de visibilidade dos chamados (regra 1 da arquitetura).
"""

import uuid
from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from typing import Any, Literal, NamedTuple

from fastapi import HTTPException
from sqlalchemy import (
    ColumnElement,
    Date,
    DateTime,
    Integer,
    and_,
    any_,
    bindparam,
    cast,
    distinct,
    func,
    not_,
    or_,
    select,
    true,
    tuple_,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, distinct_on
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, load_only
from sqlalchemy.sql.elements import Grouping

from chamados.core.permissions import P, can
from chamados.core.text import LIKE_ESCAPE, contains_pattern
from chamados.core.timezone import LOCAL_TZ
from chamados.modules.catalog.models import TicketStatus
from chamados.modules.clients.models import Client, label_of
from chamados.modules.identity.deps import Auth
from chamados.modules.identity.models import User
from chamados.modules.organization.models import Team, TeamMember
from chamados.modules.reports.schemas import (
    ClientRow,
    DayRow,
    PersonRow,
    Ref,
    Report,
    ReportOptions,
    StatusRef,
    TaskRow,
    Totals,
)
from chamados.modules.system.work_hours import WorkHours, get_work_hours
from chamados.modules.tickets.models import (
    Ticket,
    TicketCoAssignee,
    TicketComment,
    TicketEvent,
)
from chamados.modules.tickets.visibility import assigned_to, ticket_visibility_filter

TZ = LOCAL_TZ
# Os relatórios só mostram o cliente pelo nome (`label`) e o filtram pelo id público: sem os
# telefones, os e-mails e o endereço de cada um (são milhares nas opções do filtro).
CLIENT_LABEL = load_only(
    Client.public_id, Client.name, Client.trade_name, Client.city, Client.state
)
MAX_DAYS = 366


@dataclass
class Filters:
    """Cada lista vazia é "todos"; com valores, vale qualquer um deles."""

    start: date
    end: date  # inclusive
    teams: list[Team] = field(default_factory=list)
    people: list[User] = field(default_factory=list)
    clients: list[Client] = field(default_factory=list)
    no_client: bool = False  # os chamados sem cliente (junto com os de `clients`)
    statuses: list[TicketStatus] = field(default_factory=list)  # o status atual do chamado


def outside_minutes(end: datetime, minutes: int, wh: WorkHours) -> int:
    """Minutos da tarefa fora do expediente. A tarefa vai de `end - minutes` até `end` (done_at
    é quando ela terminou), no horário da máquina."""
    begin = end - timedelta(minutes=minutes)
    inside = timedelta()
    day = begin.astimezone(TZ).date()
    while day <= end.astimezone(TZ).date():
        if day.weekday() in wh.weekdays and day not in wh.holidays:
            w_start, w_end = _work_window(day, wh.start, wh.end)
            overlap = min(end, w_end) - max(begin, w_start)
            if overlap > timedelta():
                inside += overlap
        day += timedelta(days=1)
    return minutes - round(inside.total_seconds() / 60)


@lru_cache(maxsize=1024)
def _work_window(day: date, start: time, end: time) -> tuple[datetime, datetime]:
    """O expediente do dia em UTC (somar e subtrair datas no mesmo fuso do zoneinfo ignora a
    troca de horário). Em cache: num relatório de um ano, cada dia volta milhares de vezes."""
    w_start = datetime.combine(day, start, TZ).astimezone(UTC)
    return w_start, datetime.combine(day, end, TZ).astimezone(UTC)


@dataclass
class Lookups:
    """O que não muda numa requisição e mais de uma parte dela lê: o expediente e os status (na
    tela, as opções do filtro e cada `facts`, duas vezes com o "Comparar")."""

    work_hours: WorkHours
    statuses: list[TicketStatus]  # na ordem da tela


async def lookups(db: AsyncSession) -> Lookups:
    return Lookups(
        work_hours=await get_work_hours(db),
        statuses=list(await db.scalars(select(TicketStatus).order_by(TicketStatus.sort_order))),
    )


@dataclass
class Choices:
    """As opções dos filtros da tela, sem os clientes: são milhares, e a tela os busca aos
    poucos (`client_choices`), com os nomes só dos escolhidos (`client_labels`)."""

    teams: list[Ref]
    people: list[Ref]
    statuses: list[StatusRef]


async def choices(
    db: AsyncSession, auth: Auth, statuses: Sequence[TicketStatus] | None = None
) -> Choices:
    """`statuses`: os já lidos (`Lookups`); sem eles, lê."""
    actor = auth.actor
    if statuses is None:
        statuses = list(await db.scalars(select(TicketStatus).order_by(TicketStatus.sort_order)))
    people = select(User).where(User.deleted_at.is_(None))
    teams = select(Team).where(Team.is_active)
    if not can(actor, P.REPORT_VIEW_ALL):
        teams = teams.where(Team.id.in_(actor.supervises))
        people = people.where(
            or_(
                User.id == actor.user_id,
                User.id.in_(
                    select(TeamMember.user_id).where(TeamMember.team_id.in_(actor.supervises))
                ),
            )
        )
    return Choices(
        teams=[
            Ref(id=t.public_id, name=t.name) for t in await db.scalars(teams.order_by(Team.name))
        ],
        people=[
            Ref(id=u.public_id, name=u.display_name)
            for u in await db.scalars(people.order_by(User.display_name))
        ],
        statuses=[StatusRef(id=s.id, name=s.name) for s in statuses],
    )


async def options(db: AsyncSession, auth: Auth) -> ReportOptions:
    found = await choices(db, auth)
    clients = sorted(
        await db.scalars(select(Client).options(CLIENT_LABEL)), key=lambda c: c.label.casefold()
    )
    return ReportOptions(
        teams=found.teams,
        people=found.people,
        clients=[Ref(id=c.public_id, name=c.label) for c in clients],
        statuses=found.statuses,
    )


# As colunas do rótulo do cliente (`Client.label`), sem carregar o cadastro.
_LABEL_COLUMNS = (Client.public_id, Client.name, Client.trade_name, Client.city, Client.state)


async def client_labels(db: AsyncSession, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Os nomes dos clientes escolhidos num filtro; um id que não existe fica de fora."""
    wanted = list(ids)
    if not wanted:
        return {}
    rows = await db.execute(select(*_LABEL_COLUMNS).where(Client.public_id.in_(wanted)))
    return {
        public_id: label_of(name, trade_name, city, state)
        for public_id, name, trade_name, city, state in rows
    }


CLIENT_CHOICES = 50  # por busca, como no campo de cliente do chamado


async def client_choices(db: AsyncSession, q: str, exclude: Collection[uuid.UUID]) -> list[Ref]:
    """Os clientes para o filtro: pelo nome ou nome fantasia, inclusive os desativados (um
    relatório olha o passado), sem os já escolhidos; os primeiros CLIENT_CHOICES pelo nome."""
    stmt = select(*_LABEL_COLUMNS)
    if q.strip():
        term = func.unaccent(contains_pattern(q.strip()))
        stmt = stmt.where(
            or_(
                func.unaccent(Client.name).ilike(term, escape=LIKE_ESCAPE),
                func.unaccent(Client.trade_name).ilike(term, escape=LIKE_ESCAPE),
            )
        )
    if exclude:
        stmt = stmt.where(Client.public_id.not_in(list(exclude)))
    rows = await db.execute(
        stmt.order_by(
            func.lower(func.coalesce(Client.name, Client.trade_name, Client.city)), Client.id
        ).limit(CLIENT_CHOICES)
    )
    return [
        Ref(id=public_id, name=label_of(name, trade_name, city, state))
        for public_id, name, trade_name, city, state in rows
    ]


async def _find[M: (Team, User, Client)](
    db: AsyncSession, model: type[M], ids: list[uuid.UUID], message: str
) -> list[M]:
    if not ids:
        return []
    found = list(await db.scalars(select(model).where(model.public_id.in_(ids))))
    if len(found) != len(set(ids)):
        raise HTTPException(404, message)
    return found


async def resolve(
    db: AsyncSession,
    auth: Auth,
    *,
    start: date,
    end: date,
    teams: list[uuid.UUID],
    people: list[uuid.UUID],
    clients: list[uuid.UUID],
    no_client: bool,
    statuses: list[int],
) -> Filters:
    """Confere o período e as escolhas dos filtros contra o que a pessoa pode ver."""
    if end < start:
        raise HTTPException(422, "O período precisa terminar depois de começar.")
    if (end - start).days >= MAX_DAYS:
        raise HTTPException(422, "O período pode ter no máximo 366 dias.")
    if end == date.max:  # o fim do período é o começo do dia seguinte (_bounds)
        raise HTTPException(422, "Data inválida.")
    f = Filters(
        start=start,
        end=end,
        teams=await _find(db, Team, teams, "Grupo não encontrado."),
        people=await _find(db, User, people, "Usuário não encontrado."),
        clients=await _find(db, Client, clients, "Cliente não encontrado."),
        no_client=no_client,
    )
    if statuses:
        # O id é smallint: um número fora da faixa não existe (e quebraria a consulta).
        valid = [i for i in statuses if 0 < i < 2**15]
        f.statuses = list(await db.scalars(select(TicketStatus).where(TicketStatus.id.in_(valid))))
        if len(f.statuses) != len(set(statuses)):
            raise HTTPException(404, "Status não encontrado.")

    actor = auth.actor
    if not can(actor, P.REPORT_VIEW_ALL):
        if any(t.id not in actor.supervises for t in f.teams):
            raise HTTPException(403, "Você não tem permissão para esta ação.")
        others = {p.id for p in f.people} - {actor.user_id}
        if others:
            supervised = set(
                await db.scalars(
                    select(TeamMember.user_id).where(
                        TeamMember.user_id.in_(others), TeamMember.team_id.in_(actor.supervises)
                    )
                )
            )
            if others - supervised:
                raise HTTPException(403, "Você só pode ver os seus próprios números.")
    return f


def _bounds(f: Filters) -> tuple[datetime, datetime]:
    return (
        datetime.combine(f.start, time(), TZ),
        datetime.combine(f.end + timedelta(days=1), time(), TZ),
    )


def _ticket_filters(auth: Auth, f: Filters) -> list[ColumnElement[bool]]:
    conds = [ticket_visibility_filter(auth.actor)]
    if f.teams:
        conds.append(Ticket.team_id.in_([t.id for t in f.teams]))
    client_conds = []
    if f.clients:
        client_conds.append(Ticket.client_id.in_([c.id for c in f.clients]))
    if f.no_client:
        client_conds.append(Ticket.client_id.is_(None))
    if client_conds:
        conds.append(or_(*client_conds))
    if f.statuses:
        conds.append(Ticket.status_id.in_([s.id for s in f.statuses]))
    return conds


def _among(column: Any, values: Iterable[int]) -> ColumnElement[bool]:
    """`coluna = ANY(:valores)`: um parâmetro só. Num ano são dezenas de milhares de ids, e um
    `IN` com um parâmetro para cada levava mais tempo montando a consulta do que rodando."""
    among: ColumnElement[bool] = column == any_(
        bindparam(None, list(values), type_=ARRAY(column.type))
    )
    return among


def _own_or_supervised(auth: Auth, own: ColumnElement[bool]) -> ColumnElement[bool]:
    actor = auth.actor
    if can(actor, P.REPORT_VIEW_ALL):
        return true()
    return or_(own, Ticket.team_id.in_(actor.supervises))


@dataclass
class TaskFact:
    """Uma tarefa do período, com o que os relatórios agrupam."""

    author_id: int
    minutes: int
    overtime: int  # minutos fora do expediente
    done_at: datetime
    ticket_number: int
    ticket_title: str
    client_id: int | None
    team_id: int
    status_id: int

    @property
    def day(self) -> date:
        return self.done_at.astimezone(TZ).date()

    @property
    def hour(self) -> int:
        return self.done_at.astimezone(TZ).hour


FINAL = ("closed", "canceled")
# Tempo que não conta no líquido: esperando o cliente, ou concluído antes de ser reaberto.
PAUSED = ("waiting", "closed", "canceled")

# As mudanças de status no histórico: as do fluxo e do formulário e a da transferência, que leva
# o chamado de volta a Aberto (com o "de" e o "para" em `status`).
STATUS_CHANGED = or_(
    TicketEvent.event_type == "ticket.status_changed",
    and_(TicketEvent.event_type == "ticket.transferred", TicketEvent.payload.has_key("status")),
)
STATUS_CHANGE = func.coalesce(TicketEvent.payload["status"], TicketEvent.payload, type_=JSONB)


@dataclass
class TicketFact:
    """Um chamado do período: registrado, concluído, cancelado ou em aberto no fim dele. `day`: o
    dia do registro, da conclusão ou do cancelamento (no em aberto, o último dia do período);
    `people`: os responsáveis que contam, principal ou não, só os que a pessoa pode ver e os do
    filtro de pessoa; `status_id`: o atual (no em aberto, o do fim do período)."""

    number: int
    title: str
    client_id: int | None
    team_id: int
    status_id: int
    day: date
    people: set[int]
    created_at: datetime
    finished_at: datetime | None = None  # concluído ou cancelado em
    lead: int | None = None  # concluídos: minutos do registro à conclusão (tempo corrido)
    net_lead: int | None = None  # o mesmo, sem o tempo parado (PAUSED)
    reopened: bool = False
    age: int | None = None  # em aberto: minutos do registro ao fim do período
    hour: int = 0  # a hora do registro, da conclusão ou do cancelamento (no fuso da máquina)


# Os nomes do que aparece num período, com as colunas que os relatórios mostram: num ano são
# milhares de clientes, e o objeto do ORM de cada um custava mais que a consulta.
class UserName(NamedTuple):
    public_id: uuid.UUID
    display_name: str


class ClientName(NamedTuple):
    public_id: uuid.UUID
    label: str


class TeamName(NamedTuple):
    public_id: uuid.UUID
    name: str


# As partes de `facts` que vêm em linhas: todas as tarefas (a lista), as que podem ter hora extra,
# cada conjunto de chamados e o tempo líquido dos concluídos (que lê o histórico deles). Cada uma
# custa consultas próprias (o em aberto no fim é a mais larga), então quem chama pede só as que
# usa (`builder.needs`); as outras ficam vazias.
Part = Literal["tasks", "overtime", "opened", "closed", "canceled", "backlog", "net_lead"]
# As medidas que somam, e por isso vêm somadas (`Sums`) em vez de linha a linha: a mediana e a
# porcentagem precisam das linhas dos concluídos. `worked`: os chamados distintos com tarefa (a
# base das horas por chamado); não soma de um dia para a semana, então tem os agrupamentos
# próprios de semana, mês e dia da semana.
Summed = Literal["hours", "overtime", "tasks", "opened", "closed", "canceled", "backlog", "worked"]
# Os conjuntos de chamados (linhas ou contagens).
Counted = Literal["opened", "closed", "canceled", "backlog"]
COUNTED: tuple[Counted, ...] = ("opened", "closed", "canceled", "backlog")
# Os agrupamentos das somas; a semana, o mês e o dia da semana saem do dia (menos no `worked`,
# que os pede). A hora é a do dia, no fuso da máquina (0 a 23): a de término da tarefa, a do
# registro, da conclusão ou do cancelamento.
# `weekday_hour` (o mapa de calor): dia da semana × 24 + hora, de 0 a 167.
Group = Literal[
    "person", "client", "team", "status", "day", "hour", "week", "month", "weekday", "weekday_hour"
]
GROUPS: tuple[Group, ...] = (
    "person",
    "client",
    "team",
    "status",
    "day",
    "hour",
    "week",
    "month",
    "weekday",
    "weekday_hour",
)


@dataclass
class Want:
    """O que pedir ao `facts`: as linhas de cada parte e as somas de cada medida, com os
    agrupamentos (o total sempre vem)."""

    rows: set[Part] = field(default_factory=set)
    sums: dict[Summed, set[Group]] = field(default_factory=dict)


@dataclass
class Sums:
    """Uma medida somada: o total do período e, em cada agrupamento pedido, a soma de cada chave
    que aparece (um chamado conta para cada responsável, e no total uma vez só)."""

    total: int = 0
    by: dict[Group, dict[Any, int]] = field(default_factory=dict)


@dataclass
class Facts:
    """Os dados de um período, já com o escopo e os filtros, e os nomes do que aparece neles.
    `parts`: as linhas que vieram; as listas das outras ficam vazias (e o `net_lead`, None).
    `overtime_tasks`: as tarefas que podem ter hora extra (as que não cabem inteiras numa janela
    do expediente; todas, quando vieram todas); as outras têm zero. `sums`: as medidas pedidas."""

    parts: frozenset[Part]
    work_hours: WorkHours
    tasks: list[TaskFact]
    overtime_tasks: list[TaskFact]
    opened: list[TicketFact]
    closed: list[TicketFact]
    canceled: list[TicketFact]
    backlog: list[TicketFact]
    sums: dict[Summed, Sums]
    users: dict[int, UserName]
    clients: dict[int, ClientName]
    teams: dict[int, TeamName]
    statuses: dict[int, TicketStatus]


def group_keys(fact: TaskFact | TicketFact, group: Group) -> Iterable[Any]:
    """As chaves de uma tarefa ou de um chamado num agrupamento: a pessoa da tarefa é quem a fez;
    a do chamado, cada responsável que conta."""
    if group == "person":
        return (fact.author_id,) if isinstance(fact, TaskFact) else fact.people
    if group == "client":
        return (fact.client_id,)
    if group == "team":
        return (fact.team_id,)
    if group == "status":
        return (fact.status_id,)
    if group == "hour":
        return (fact.hour,)
    if group == "week":
        return (fact.day - timedelta(days=fact.day.weekday()),)
    if group == "month":
        return (fact.day.replace(day=1),)
    if group == "weekday":
        return (fact.day.weekday(),)
    if group == "weekday_hour":
        return (fact.day.weekday() * 24 + fact.hour,)
    return (fact.day,)


def distinct_tickets(tasks: Iterable[TaskFact], groups: Iterable[Group]) -> Sums:
    """Os chamados distintos com tarefa (`worked`), das linhas: cada chamado conta uma vez em
    cada chave e no total."""
    total: set[int] = set()
    seen: dict[Group, dict[Any, set[int]]] = {g: defaultdict(set) for g in groups}
    for task in tasks:
        total.add(task.ticket_number)
        for group, by in seen.items():
            for key in group_keys(task, group):
                by[key].add(task.ticket_number)
    return Sums(
        total=len(total), by={g: {k: len(v) for k, v in by.items()} for g, by in seen.items()}
    )


def add_up(amounts: Iterable[tuple[TaskFact | TicketFact, int]], groups: Iterable[Group]) -> Sums:
    """As somas a partir das linhas, quando elas já vieram ou só elas dão o número (a hora extra
    de cada tarefa, o status do em aberto no fim)."""
    sums = Sums(by={g: {} for g in groups})
    for fact, amount in amounts:
        sums.total += amount
        for group, by in sums.by.items():
            for key in group_keys(fact, group):
                by[key] = by.get(key, 0) + amount
    return sums


def net_minutes(
    created_at: datetime,
    closed_at: datetime,
    changes: list[tuple[datetime, int, int]],
    kinds: dict[int, str],
) -> int:
    """Minutos do registro à conclusão sem o tempo parado: em Aguardando ou concluído (ou
    cancelado) antes de ser reaberto (docs/14 §14.3). `changes`: as mudanças de status (quando,
    de, para) em ordem. Uma conclusão com data informada pode ter o evento depois dela: o que
    passa de `closed_at` não conta."""
    paused = timedelta()
    start = created_at
    status = changes[0][1] if changes else None
    for at, _, after in changes:
        end = min(at, closed_at)
        if end > start and status is not None and kinds.get(status) in PAUSED:
            paused += end - start
        start, status = max(start, end), after
    if closed_at > start and status is not None and kinds.get(status) in PAUSED:
        paused += closed_at - start
    return max(0, round((closed_at - created_at - paused).total_seconds() / 60))


def _local_day(moment: Any) -> ColumnElement[date]:
    """O dia de um instante no fuso da máquina: o `day` das linhas, no banco."""
    return cast(func.timezone(TZ.key, moment), Date)


def _local_hour(moment: Any) -> ColumnElement[int]:
    """A hora (0 a 23) de um instante no fuso da máquina: a `hour` das linhas, no banco."""
    return cast(func.extract("hour", func.timezone(TZ.key, moment)), Integer)


def _local_weekday_hour(moment: Any) -> ColumnElement[int]:
    """O dia da semana × 24 + a hora de um instante no fuso da máquina (o `weekday_hour`)."""
    local = func.timezone(TZ.key, moment)
    weekday = cast(func.extract("isodow", local), Integer) - 1  # 0 = segunda
    return weekday * 24 + _local_hour(moment)


def _task_group(group: Group) -> Any:
    if group == "person":
        return TicketComment.author_id
    if group == "client":
        return Ticket.client_id
    if group == "team":
        return Ticket.team_id
    if group == "status":
        return Ticket.status_id
    if group == "hour":
        return _local_hour(TicketComment.done_at)
    if group == "weekday_hour":
        return _local_weekday_hour(TicketComment.done_at)
    local = func.timezone(TZ.key, TicketComment.done_at)
    if group in ("week", "month"):  # a segunda-feira ou o dia 1º, como o `group_keys`
        return cast(func.date_trunc(group, local), Date)
    if group == "weekday":  # 0 = segunda, como o `date.weekday()`
        return cast(func.extract("isodow", local), Integer) - 1
    return _local_day(TicketComment.done_at)


def _may_have_overtime(f: Filters, wh: WorkHours) -> ColumnElement[bool]:
    """As tarefas que podem ter hora extra: com tempo e que não cabem inteiras na janela do
    expediente do dia em que terminam (as outras têm zero). As janelas são as do mesmo
    `_work_window` do `outside_minutes`, uma por dia do período (nenhuma nos dias de folga e nos
    feriados), e cada tarefa pega a do seu dia pelo índice; a hora extra das que passam continua
    sendo calculada em Python."""
    starts: list[datetime | None] = []
    ends: list[datetime | None] = []
    day = f.start
    while day <= f.end:
        window = (
            _work_window(day, wh.start, wh.end)
            if day.weekday() in wh.weekdays and day not in wh.holidays
            else (None, None)
        )
        starts.append(window[0])
        ends.append(window[1])
        day += timedelta(days=1)
    windows = ARRAY(DateTime(timezone=True))
    index = _local_day(TicketComment.done_at) - bindparam(None, f.start, type_=Date) + 1
    # Entre parênteses: o PostgreSQL não aceita o índice logo depois do `::timestamptz[]`.
    w_start = Grouping(bindparam(None, starts, type_=windows))[index]
    w_end = Grouping(bindparam(None, ends, type_=windows))[index]
    spent = func.make_interval(0, 0, 0, 0, 0, TicketComment.time_spent_minutes)
    inside = and_(
        w_start.is_not(None),
        TicketComment.done_at - spent >= w_start,
        TicketComment.done_at <= w_end,
    )
    return and_(TicketComment.time_spent_minutes > 0, not_(inside))


async def _task_rows(
    db: AsyncSession, conds: list[ColumnElement[bool]], wh: WorkHours
) -> list[TaskFact]:
    # Só as colunas usadas: a tarefa inteira traria o texto (até 50 mil caracteres) e o autor de
    # cada linha; os nomes vêm depois, uma vez cada.
    rows = await db.execute(
        select(
            TicketComment.author_id,
            TicketComment.time_spent_minutes,
            TicketComment.done_at,
            Ticket.number,
            Ticket.title,
            Ticket.client_id,
            Ticket.team_id,
            Ticket.status_id,
        )
        .join(Ticket, Ticket.id == TicketComment.ticket_id)
        .where(*conds)
        .order_by(TicketComment.done_at)
    )
    return [
        TaskFact(
            author_id=author_id,
            minutes=spent or 0,
            overtime=outside_minutes(done_at, spent, wh) if spent else 0,
            done_at=done_at,
            ticket_number=number,
            ticket_title=title,
            client_id=client_id,
            team_id=team_id,
            status_id=status_id,
        )
        for author_id, spent, done_at, number, title, client_id, team_id, status_id in rows
    ]


def _grouping_sets(exprs: Sequence[ColumnElement[Any]]) -> Any:
    """Cada expressão num conjunto, mais o total: uma consulta só para todos os agrupamentos."""
    return func.grouping_sets(*(tuple_(e) for e in exprs), tuple_())


async def _task_sums(
    db: AsyncSession, conds: list[ColumnElement[bool]], groups: Collection[Group], *, worked: bool
) -> tuple[Sums, Sums, Sums]:
    """As horas, as tarefas e, com `worked`, os chamados distintos com tarefa somados no banco
    (sem trazer as linhas): os agrupamentos pedidos e o total num GROUPING SETS. Cada
    agrupamento é uma expressão fixa (`_task_group`). O `count(distinct)` só quando pedido: ele
    ordena as tarefas de cada agrupamento."""
    names = list(groups)
    exprs = [_task_group(g) for g in names]
    minutes = func.coalesce(func.sum(TicketComment.time_spent_minutes), 0)
    counts = [func.count(), minutes]
    if worked:
        counts.append(func.count(distinct(TicketComment.ticket_id)))
    query = (
        select(*exprs, *(func.grouping(e) for e in exprs), *counts)
        .select_from(TicketComment)
        .join(Ticket, Ticket.id == TicketComment.ticket_id)
        .where(*conds)
        .group_by(_grouping_sets(exprs))
    )
    hours, tasks, tickets = (Sums(by={g: {} for g in names}) for _ in range(3))
    n = len(names)
    for row in await db.execute(query):
        keys, flags = row[:n], row[n : 2 * n]
        count, total = row[2 * n], row[2 * n + 1]
        distinct_count = row[2 * n + 2] if worked else 0
        # A linha de um agrupamento tem o GROUPING() dele em 0; a do total, todos em 1.
        i = next((i for i, flag in enumerate(flags) if flag == 0), None)
        if i is None:
            tasks.total, hours.total, tickets.total = count, total, distinct_count
        else:
            tasks.by[names[i]][keys[i]] = count
            hours.by[names[i]][keys[i]] = total
            tickets.by[names[i]][keys[i]] = distinct_count
    return hours, tasks, tickets


TICKET_DAY = {
    "opened": Ticket.created_at,
    "closed": Ticket.closed_at,
    "canceled": Ticket.canceled_at,
}


async def _ticket_sums(
    db: AsyncSession,
    conds: list[ColumnElement[bool]],
    sets: dict[Counted, ColumnElement[bool]],
    groups: Collection[Group],
    allowed: set[int] | None,
) -> dict[Summed, Sums]:
    """Os registrados, concluídos e cancelados contados no banco, quando as linhas deles não são
    precisas: os agrupamentos e o total num GROUPING SETS, cada conjunto com o seu `count(*)
    FILTER`. O dia é o do registro, da conclusão ou do cancelamento; a pessoa, cada responsável
    que a pessoa pode ver (o principal aqui, os outros numa segunda consulta), e o total conta o
    chamado uma vez."""
    parts = list(sets)
    columns: dict[Group, Any] = {
        "client": Ticket.client_id,
        "team": Ticket.team_id,
        "status": Ticket.status_id,
    }
    targets: list[tuple[Group, Counted | None]] = [(g, None) for g in columns if g in groups]
    exprs: list[Any] = [columns[g] for g, _ in targets]
    if "person" in groups:
        targets.append(("person", None))
        exprs.append(Ticket.assignee_id)
    locals_: tuple[tuple[Group, Any], ...] = (
        ("day", _local_day),
        ("hour", _local_hour),
        ("weekday_hour", _local_weekday_hour),
    )
    for group, local in locals_:
        if group in groups:
            for part in parts:
                targets.append((group, part))
                exprs.append(local(TICKET_DAY[part]))
    counts = [func.count().filter(sets[p]) for p in parts]
    query = (
        select(*exprs, *(func.grouping(e) for e in exprs), *counts)
        .select_from(Ticket)
        .join(TicketStatus, TicketStatus.id == Ticket.status_id)
        .where(*conds, or_(*sets.values()))
        .group_by(_grouping_sets(exprs))
    )
    sums: dict[Summed, Sums] = {p: Sums(by={g: {} for g in groups}) for p in parts}

    def count(group: Group, key: Any, part: Counted, amount: int) -> None:
        if amount and (group != "person" or allowed is None or key in allowed):
            by = sums[part].by[group]
            by[key] = by.get(key, 0) + amount

    n = len(exprs)
    for row in await db.execute(query):
        keys, flags, amounts = row[:n], row[n : 2 * n], row[2 * n :]
        i = next((i for i, flag in enumerate(flags) if flag == 0), None)
        if i is None:
            for part, amount in zip(parts, amounts, strict=True):
                sums[part].total = amount
            continue
        group, only = targets[i]
        for part, amount in zip(parts, amounts, strict=True):
            if only is None or only == part:
                count(group, keys[i], part, amount)
    if "person" in groups:
        # Um alias: o filtro de visibilidade tem um EXISTS nos corresponsáveis, que se
        # correlacionaria com esta tabela e ficaria sem FROM.
        co = aliased(TicketCoAssignee)
        others = await db.execute(
            select(co.user_id, *counts)
            .select_from(co)
            .join(Ticket, Ticket.id == co.ticket_id)
            .join(TicketStatus, TicketStatus.id == Ticket.status_id)
            .where(*conds, or_(*sets.values()), co.user_id != Ticket.assignee_id)
            .group_by(co.user_id)
        )
        for user_id, *co_amounts in others:
            for part, amount in zip(parts, co_amounts, strict=True):
                count("person", user_id, part, amount)
    return sums


async def facts(
    db: AsyncSession,
    auth: Auth,
    f: Filters,
    want: Want,
    known: Lookups | None = None,
) -> Facts:
    """Os dados do período: as linhas e as somas pedidas em `want` (as outras listas ficam
    vazias). `known`: o expediente e os status já lidos na requisição; sem eles, lê."""
    known = known or await lookups(db)
    wh = known.work_hours
    since, until = _bounds(f)
    me = auth.user.id
    people_ids = {p.id for p in f.people}
    parts: set[Part] = set(want.rows)
    if "backlog" in want.sums:  # o status do fim do período só sai das linhas
        parts.add("backlog")
    sums: dict[Summed, Sums] = {}

    allowed_cache: list[set[int] | None] = []

    async def allowed() -> set[int] | None:
        """Os responsáveis que contam: os do filtro de pessoa; sem ele, quem não vê tudo só conta
        a si e as pessoas dos grupos que supervisiona (um colega de outro grupo pode ser
        corresponsável)."""
        if not allowed_cache:
            if people_ids:
                allowed_cache.append(people_ids)
            elif can(auth.actor, P.REPORT_VIEW_ALL):
                allowed_cache.append(None)
            else:
                supervised = await db.scalars(
                    select(TeamMember.user_id).where(TeamMember.team_id.in_(auth.actor.supervises))
                )
                allowed_cache.append({me} | set(supervised))
        return allowed_cache[0]

    # --- tarefas do período (horas, horas extras) ---
    task_conds = [
        *_ticket_filters(auth, f),
        _own_or_supervised(auth, TicketComment.author_id == me),
        TicketComment.deleted_at.is_(None),
        TicketComment.done_at >= since,
        TicketComment.done_at < until,
    ]
    if people_ids:
        task_conds.append(TicketComment.author_id.in_(people_ids))
    tasks: list[TaskFact] = []
    overtime_tasks: list[TaskFact] = []
    if "tasks" in parts:
        tasks = overtime_tasks = await _task_rows(db, task_conds, wh)
        parts.add("overtime")
    elif "overtime" in parts or "overtime" in want.sums:
        overtime_tasks = await _task_rows(db, [*task_conds, _may_have_overtime(f, wh)], wh)
        parts.add("overtime")
    task_measures: tuple[Summed, ...] = ("hours", "tasks", "overtime", "worked")
    task_groups: set[Group] = set().union(*(want.sums.get(m, set()) for m in task_measures))
    if any(m in want.sums for m in task_measures):
        if "tasks" in parts:  # as linhas já vieram
            sums["hours"] = add_up(((t, t.minutes) for t in tasks), task_groups)
            sums["tasks"] = add_up(((t, 1) for t in tasks), task_groups)
            worked = distinct_tickets(tasks, task_groups) if "worked" in want.sums else Sums()
        else:
            sums["hours"], sums["tasks"], worked = await _task_sums(
                db, task_conds, task_groups, worked="worked" in want.sums
            )
        if "worked" in want.sums:
            sums["worked"] = worked
    if "overtime" in want.sums:
        # Só as que podem ter hora extra somam; as chaves das outras (com zero) vêm das tarefas,
        # para o bloco mostrar as mesmas linhas de quando todas passavam pelo Python.
        overtime = add_up(((t, t.overtime) for t in overtime_tasks), task_groups)
        for group, by in overtime.by.items():
            for key in sums["tasks"].by[group]:
                by.setdefault(key, 0)
        sums["overtime"] = overtime

    # --- chamados: registrados, concluídos e cancelados no período, em aberto no fim ---
    ticket_conds = [*_ticket_filters(auth, f), _own_or_supervised(auth, assigned_to(me))]
    if people_ids:
        ticket_conds.append(or_(*(assigned_to(i) for i in people_ids)))

    # Os quatro conjuntos numa varredura só: as condições num OR e cada chamado separado depois,
    # pelas mesmas datas. Cada consulta à parte passava por todos os chamados com o filtro de
    # visibilidade (os concluídos e os cancelados não têm índice pela data).
    #
    # Em aberto no fim: registrados até lá e não concluídos nem cancelados antes dele (pelas
    # datas de conclusão e cancelamento, as mesmas das medidas). O status de então é o "de" da
    # primeira mudança depois do fim; sem mudança, o atual.
    sets: dict[Counted, ColumnElement[bool]] = {
        "opened": and_(Ticket.created_at >= since, Ticket.created_at < until),
        "closed": and_(
            TicketStatus.kind == "closed", Ticket.closed_at >= since, Ticket.closed_at < until
        ),
        "canceled": and_(
            TicketStatus.kind == "canceled",
            Ticket.canceled_at >= since,
            Ticket.canceled_at < until,
        ),
        "backlog": and_(
            Ticket.created_at < until,
            not_(and_(TicketStatus.kind == "closed", Ticket.closed_at < until)),
            not_(and_(TicketStatus.kind == "canceled", Ticket.canceled_at < until)),
        ),
    }
    wanted = [cond for part, cond in sets.items() if part in parts]
    found: Sequence[Any] = ()
    if wanted:
        query = (
            select(
                Ticket.id,
                Ticket.number,
                Ticket.title,
                Ticket.client_id,
                Ticket.team_id,
                Ticket.status_id,
                Ticket.assignee_id,
                Ticket.created_at,
                Ticket.closed_at,
                Ticket.canceled_at,
                Ticket.reopened_count,
                TicketStatus.kind,
            )
            .join(TicketStatus, TicketStatus.id == Ticket.status_id)
            .where(*ticket_conds, or_(*wanted))
            .order_by(Ticket.number)
        )
        found = (await db.execute(query)).all()

    def within(moment: datetime | None) -> bool:
        return moment is not None and since <= moment < until

    def open_at_end(r: Any) -> bool:
        """O `not_` de "backlog": sem a data, o concluído (ou cancelado) também fica de fora,
        como no SQL (NOT de NULL não é verdadeiro)."""
        finished = {"closed": r.closed_at, "canceled": r.canceled_at}
        if r.kind not in finished:
            return True
        moment = finished[r.kind]
        return moment is not None and moment >= until

    opened = [r for r in found if "opened" in parts and within(r.created_at)]
    closed = [r for r in found if "closed" in parts and r.kind == "closed" and within(r.closed_at)]
    canceled = [
        r for r in found if "canceled" in parts and r.kind == "canceled" and within(r.canceled_at)
    ]
    candidates = [
        r for r in found if "backlog" in parts and r.created_at < until and open_at_end(r)
    ]
    # Um dicionário novo: os removidos depois do período entram nele (abaixo).
    statuses = {s.id: s for s in known.statuses}
    kinds = {i: s.kind for i, s in statuses.items()}
    status_at_end: dict[int, int] = {}
    if candidates:
        first_change = await db.execute(
            select(
                TicketEvent.ticket_id,
                STATUS_CHANGE["from"]["id"].as_integer(),
                STATUS_CHANGE["from"]["name"].as_string(),
            )
            .where(
                STATUS_CHANGED,
                TicketEvent.created_at >= until,
                _among(TicketEvent.ticket_id, [r.id for r in candidates]),
            )
            .ext(distinct_on(TicketEvent.ticket_id))
            .order_by(TicketEvent.ticket_id, TicketEvent.created_at)
        )
        for ticket_id, status_id, name in first_change:
            status_at_end[ticket_id] = status_id
            # Removido depois: fica o nome da data da mudança (sem o comportamento, conta aberto).
            if status_id not in statuses:
                statuses[status_id] = TicketStatus(id=status_id, name=name, kind="")
    backlog = [
        r for r in candidates if kinds.get(status_at_end.get(r.id, r.status_id)) not in FINAL
    ]

    # As mudanças de status dos concluídos, para o tempo líquido.
    changes: dict[int, list[tuple[datetime, int, int]]] = defaultdict(list)
    net = "net_lead" in parts
    if closed and net:
        events = await db.execute(
            select(
                TicketEvent.ticket_id,
                TicketEvent.created_at,
                STATUS_CHANGE["from"]["id"].as_integer(),
                STATUS_CHANGE["to"]["id"].as_integer(),
            )
            .where(STATUS_CHANGED, _among(TicketEvent.ticket_id, [r.id for r in closed]))
            .order_by(TicketEvent.ticket_id, TicketEvent.created_at)
        )
        for ticket_id, at, before, after in events:
            changes[ticket_id].append((at, before, after))

    # Cada responsável (principal ou não) conta o chamado.
    assignees: dict[int, set[int]] = defaultdict(set)
    for r in (*opened, *closed, *canceled, *backlog):
        if r.assignee_id:
            assignees[r.id].add(r.assignee_id)
    if assignees:
        co = await db.execute(
            select(TicketCoAssignee.ticket_id, TicketCoAssignee.user_id).where(
                _among(TicketCoAssignee.ticket_id, assignees)
            )
        )
        for ticket_id, user_id in co:
            assignees[ticket_id].add(user_id)
    seen = await allowed() if assignees else None

    def fact(r: Any, moment: datetime, status_id: int | None = None, **extra: Any) -> TicketFact:
        people = assignees[r.id]
        return TicketFact(
            number=r.number,
            title=r.title,
            client_id=r.client_id,
            team_id=r.team_id,
            status_id=status_id or r.status_id,
            day=moment.astimezone(TZ).date(),
            hour=moment.astimezone(TZ).hour,
            people=people if seen is None else people & seen,
            created_at=r.created_at,
            **extra,
        )

    end_moment = until - timedelta(microseconds=1)  # o último dia do período
    ticket_facts: dict[Counted, list[TicketFact]] = {
        "opened": [fact(r, r.created_at) for r in opened],
        "closed": [
            fact(
                r,
                r.closed_at,
                finished_at=r.closed_at,
                lead=round((r.closed_at - r.created_at).total_seconds() / 60),
                net_lead=net_minutes(r.created_at, r.closed_at, changes[r.id], kinds)
                if net
                else None,
                reopened=r.reopened_count > 0,
            )
            for r in closed
        ],
        "canceled": [fact(r, r.canceled_at, finished_at=r.canceled_at) for r in canceled],
        "backlog": [
            fact(
                r,
                end_moment,
                status_id=status_at_end.get(r.id, r.status_id),
                age=round((until - r.created_at).total_seconds() / 60),
            )
            for r in backlog
        ],
    }
    # As contagens: das linhas, quando vieram; as outras, no banco.
    in_sql: dict[Counted, ColumnElement[bool]] = {}
    for part in COUNTED:
        if part not in want.sums:
            continue
        if part in parts:
            sums[part] = add_up(((t, 1) for t in ticket_facts[part]), want.sums[part])
        else:
            in_sql[part] = sets[part]
    if in_sql:
        groups: set[Group] = set().union(*(want.sums[p] for p in in_sql))
        seen_sql = await allowed() if "person" in groups else None
        sums.update(await _ticket_sums(db, ticket_conds, in_sql, groups, seen_sql))

    # --- nomes: dos que aparecem nas linhas e nas somas ---
    every: list[TaskFact | TicketFact] = [
        *overtime_tasks,
        *(t for v in ticket_facts.values() for t in v),
    ]
    user_ids = {t.author_id for t in overtime_tasks} | {
        u for v in ticket_facts.values() for t in v for u in t.people
    }
    client_ids = {t.client_id for t in every if t.client_id is not None}
    team_ids = {t.team_id for t in every}
    for measure in sums.values():
        user_ids |= set(measure.by.get("person", {}))
        client_ids |= {c for c in measure.by.get("client", {}) if c is not None}
        team_ids |= set(measure.by.get("team", {}))
    return Facts(
        parts=frozenset(parts),
        work_hours=wh,
        tasks=tasks,
        overtime_tasks=overtime_tasks,
        opened=ticket_facts["opened"],
        closed=ticket_facts["closed"],
        canceled=ticket_facts["canceled"],
        backlog=ticket_facts["backlog"],
        sums=sums,
        users={
            i: UserName(public_id, name)
            for i, public_id, name in await db.execute(
                select(User.id, User.public_id, User.display_name).where(_among(User.id, user_ids))
            )
        },
        clients={
            i: ClientName(public_id, label_of(name, trade_name, city, state))
            for i, public_id, name, trade_name, city, state in await db.execute(
                select(Client.id, *_LABEL_COLUMNS).where(_among(Client.id, client_ids))
            )
        },
        teams={
            i: TeamName(public_id, name)
            for i, public_id, name in await db.execute(
                select(Team.id, Team.public_id, Team.name).where(_among(Team.id, team_ids))
            )
        },
        statuses=statuses,
    )


@dataclass
class ClientTicket:
    """Um chamado do relatório para o cliente (docs/14 §14.8.5): só o que o cliente pode ver."""

    number: int
    title: str
    created_at: datetime
    closed_at: datetime | None  # só se está concluído
    status: str
    minutes: int  # as horas das tarefas do período
    people: list[str]  # os responsáveis (o modelo escolhe se aparecem)


async def client_tickets(db: AsyncSession, auth: Auth, data: Facts) -> list[ClientTicket]:
    """Os chamados do período para o cliente: os com tarefa, os registrados e os concluídos nele
    (já com os filtros e o escopo de `data`), com as horas das tarefas do período."""
    minutes: dict[int, int] = defaultdict(int)
    for t in data.tasks:
        minutes[t.ticket_number] += t.minutes
    numbers = set(minutes) | {t.number for t in (*data.opened, *data.closed)}
    if not numbers:
        return []
    rows = await db.execute(
        select(Ticket.id, Ticket.number, Ticket.title, Ticket.created_at, Ticket.closed_at)
        .add_columns(TicketStatus.name, TicketStatus.kind, Ticket.assignee_id)
        .join(TicketStatus, TicketStatus.id == Ticket.status_id)
        .where(_among(Ticket.number, numbers), ticket_visibility_filter(auth.actor))
        .order_by(Ticket.number)
    )
    tickets = rows.all()
    people: dict[int, set[int]] = defaultdict(set)
    for r in tickets:
        people[r.id].add(r.assignee_id)
    co = await db.execute(
        select(TicketCoAssignee.ticket_id, TicketCoAssignee.user_id).where(
            _among(TicketCoAssignee.ticket_id, [r.id for r in tickets])
        )
    )
    for ticket_id, user_id in co:
        people[ticket_id].add(user_id)
    names = {
        u.id: u.display_name
        for u in await db.scalars(
            select(User).where(_among(User.id, {u for ids in people.values() for u in ids}))
        )
    }
    return [
        ClientTicket(
            number=r.number,
            title=r.title,
            created_at=r.created_at,
            closed_at=r.closed_at if r.kind == "closed" else None,
            status=r.name,
            minutes=minutes.get(r.number, 0),
            people=sorted(names[u] for u in people[r.id]),
        )
        for r in tickets
    ]


# O que `build` soma (as telas prontas da §14.7): horas, tarefas e hora extra por pessoa, cliente
# e dia, os registrados por cliente e os concluídos por cliente e por responsável.
BUILD_SUMS: dict[Summed, set[Group]] = {
    "hours": {"person", "client", "day"},
    "tasks": {"person", "client"},
    "overtime": {"person", "day"},
    "opened": {"client"},
    "closed": {"person", "client"},
}


async def build(db: AsyncSession, auth: Auth, f: Filters, *, all_tasks: bool = False) -> Report:
    """Os números das telas prontas, da API e do PDF. `all_tasks`: também a lista de todas as
    tarefas (`Report.tasks`, para o CSV)."""
    want = Want(rows={"tasks"} if all_tasks else set(), sums=dict(BUILD_SUMS))
    data = await facts(db, auth, f, want)
    s = data.sums

    # As somas em Counter, e os modelos só no fim: num ano são milhares de linhas, e cada `+=`
    # num modelo do pydantic passa pela validação da atribuição.
    def add(rows: dict[Any, Counter[str]], group: Group, fields: dict[str, Summed]) -> None:
        for name, measure in fields.items():
            for key, amount in s[measure].by[group].items():
                rows[key][name] += amount

    people: dict[int, Counter[str]] = defaultdict(Counter)
    add(
        people,
        "person",
        {
            "minutes": "hours",
            "tasks": "tasks",
            "overtime_minutes": "overtime",
            "tickets_closed": "closed",
        },
    )
    clients: dict[int | None, Counter[str]] = defaultdict(Counter)
    for client_id in s["tasks"].by["client"]:  # quem tem tarefa aparece, mesmo sem tempo
        clients[client_id]["minutes"] += 0
    add(
        clients,
        "client",
        {"minutes": "hours", "tickets_opened": "opened", "tickets_closed": "closed"},
    )
    days = {f.start + timedelta(days=i): Counter[str]() for i in range((f.end - f.start).days + 1)}
    add(days, "day", {"minutes": "hours", "overtime_minutes": "overtime"})

    def client_name(client_id: int | None) -> str | None:
        return data.clients[client_id].label if client_id is not None else None

    def row(t: TaskFact) -> TaskRow:
        return TaskRow(
            ticket_number=t.ticket_number,
            ticket_title=t.ticket_title,
            client=client_name(t.client_id),
            person=data.users[t.author_id].display_name,
            done_at=t.done_at,
            minutes=t.minutes,
            overtime_minutes=t.overtime,
        )

    overtime_tasks = [row(t) for t in data.overtime_tasks if t.overtime]
    task_rows = [row(t) for t in data.tasks]

    person_rows = [
        PersonRow(
            id=data.users[user_id].public_id,
            name=data.users[user_id].display_name,
            minutes=s["minutes"],
            overtime_minutes=s["overtime_minutes"],
            tasks=s["tasks"],
            tickets_closed=s["tickets_closed"],
        )
        for user_id, s in sorted(people.items())
    ]
    client_rows = [
        ClientRow(
            id=data.clients[client_id].public_id if client_id is not None else None,
            name=client_name(client_id),
            minutes=s["minutes"],
            tickets_opened=s["tickets_opened"],
            tickets_closed=s["tickets_closed"],
        )
        for client_id, s in clients.items()
    ]
    return Report(
        start=f.start,
        end=f.end,
        work_hours=data.work_hours,
        totals=Totals(
            minutes=s["hours"].total,
            overtime_minutes=s["overtime"].total,
            tasks=s["tasks"].total,
            tickets_opened=s["opened"].total,
            tickets_closed=s["closed"].total,
        ),
        people=sorted(person_rows, key=lambda p: (-p.minutes, p.name)),
        clients=sorted(
            client_rows,
            key=lambda c: (-c.minutes, -c.tickets_opened, c.name is None, c.name or ""),
        ),
        days=[
            DayRow(date=d, minutes=s["minutes"], overtime_minutes=s["overtime_minutes"])
            for d, s in days.items()
        ],
        overtime_tasks=overtime_tasks,
        tasks=task_rows,
    )
