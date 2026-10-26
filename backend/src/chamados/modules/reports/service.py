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
from sqlalchemy import ColumnElement, and_, any_, bindparam, func, not_, or_, select, true
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, distinct_on
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

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


# As partes de `facts`: as tarefas, cada conjunto de chamados e o tempo líquido dos concluídos
# (que lê o histórico deles). Cada uma custa consultas próprias (o em aberto no fim é a mais
# larga), então quem chama pede só as que usa (`builder.needs`); as outras ficam vazias.
Part = Literal["tasks", "opened", "closed", "canceled", "backlog", "net_lead"]


@dataclass
class Facts:
    """Os dados de um período, já com o escopo e os filtros, e os nomes do que aparece neles.
    `parts`: as partes pedidas; as listas das outras ficam vazias (e o `net_lead`, None)."""

    parts: frozenset[Part]
    work_hours: WorkHours
    tasks: list[TaskFact]
    opened: list[TicketFact]
    closed: list[TicketFact]
    canceled: list[TicketFact]
    backlog: list[TicketFact]
    users: dict[int, UserName]
    clients: dict[int, ClientName]
    teams: dict[int, TeamName]
    statuses: dict[int, TicketStatus]


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


async def facts(
    db: AsyncSession,
    auth: Auth,
    f: Filters,
    parts: Collection[Part],
    known: Lookups | None = None,
) -> Facts:
    """Os dados do período: só as `parts` pedidas (as outras listas ficam vazias). `known`: o
    expediente e os status já lidos na requisição; sem eles, lê."""
    known = known or await lookups(db)
    wh = known.work_hours
    since, until = _bounds(f)
    me = auth.user.id
    people_ids = {p.id for p in f.people}

    # --- tarefas do período (horas, horas extras) ---
    tasks: list[TaskFact] = []
    if "tasks" in parts:
        task_conds = [
            *_ticket_filters(auth, f),
            _own_or_supervised(auth, TicketComment.author_id == me),
            TicketComment.deleted_at.is_(None),
            TicketComment.done_at >= since,
            TicketComment.done_at < until,
        ]
        if people_ids:
            task_conds.append(TicketComment.author_id.in_(people_ids))
        # Só as colunas usadas: a tarefa inteira traria o texto (até 50 mil caracteres) e o
        # autor de cada linha; os nomes vêm depois, uma vez cada.
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
            .where(*task_conds)
            .order_by(TicketComment.done_at)
        )
        tasks = [
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
    sets: dict[Part, ColumnElement[bool]] = {
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
    allowed: set[int] | None = None
    if people_ids:
        allowed = people_ids
    elif assignees and not can(auth.actor, P.REPORT_VIEW_ALL):
        # Um colega de outro grupo pode ser corresponsável: só entra quem a pessoa pode ver.
        allowed = {me} | set(
            await db.scalars(
                select(TeamMember.user_id).where(TeamMember.team_id.in_(auth.actor.supervises))
            )
        )

    def fact(r: Any, moment: datetime, status_id: int | None = None, **extra: Any) -> TicketFact:
        people = assignees[r.id]
        return TicketFact(
            number=r.number,
            title=r.title,
            client_id=r.client_id,
            team_id=r.team_id,
            status_id=status_id or r.status_id,
            day=moment.astimezone(TZ).date(),
            people=people if allowed is None else people & allowed,
            created_at=r.created_at,
            **extra,
        )

    end_moment = until - timedelta(microseconds=1)  # o último dia do período
    opened_facts = [fact(r, r.created_at) for r in opened]
    closed_facts = [
        fact(
            r,
            r.closed_at,
            finished_at=r.closed_at,
            lead=round((r.closed_at - r.created_at).total_seconds() / 60),
            net_lead=net_minutes(r.created_at, r.closed_at, changes[r.id], kinds) if net else None,
            reopened=r.reopened_count > 0,
        )
        for r in closed
    ]
    canceled_facts = [fact(r, r.canceled_at, finished_at=r.canceled_at) for r in canceled]
    backlog_facts = [
        fact(
            r,
            end_moment,
            status_id=status_at_end.get(r.id, r.status_id),
            age=round((until - r.created_at).total_seconds() / 60),
        )
        for r in backlog
    ]

    # --- nomes ---
    ticket_facts = [*opened_facts, *closed_facts, *canceled_facts, *backlog_facts]
    every: list[TaskFact | TicketFact] = [*tasks, *ticket_facts]
    user_ids = {t.author_id for t in tasks} | {u for t in ticket_facts for u in t.people}
    client_ids = {t.client_id for t in every if t.client_id is not None}
    team_ids = {t.team_id for t in every}
    return Facts(
        parts=frozenset(parts),
        work_hours=wh,
        tasks=tasks,
        opened=opened_facts,
        closed=closed_facts,
        canceled=canceled_facts,
        backlog=backlog_facts,
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


# O que `build` soma: as tarefas, os registrados e os concluídos (com os responsáveis).
BUILD_PARTS: frozenset[Part] = frozenset({"tasks", "opened", "closed"})


async def build(db: AsyncSession, auth: Auth, f: Filters, *, all_tasks: bool = False) -> Report:
    """Os números das telas prontas, da API e do PDF. `all_tasks`: também a lista de todas as
    tarefas (`Report.tasks`, para o CSV)."""
    data = await facts(db, auth, f, BUILD_PARTS)
    # As somas em Counter, e os modelos só no fim: num ano são dezenas de milhares de tarefas, e
    # cada `+=` num modelo do pydantic passa pela validação da atribuição.
    people: dict[int, Counter[str]] = defaultdict(Counter)
    clients: dict[int | None, Counter[str]] = defaultdict(Counter)
    days = {f.start + timedelta(days=i): Counter[str]() for i in range((f.end - f.start).days + 1)}
    overtime_tasks: list[TaskRow] = []
    task_rows: list[TaskRow] = []

    def client_name(client_id: int | None) -> str | None:
        return data.clients[client_id].label if client_id is not None else None

    for t in data.tasks:
        p = people[t.author_id]
        p["tasks"] += 1
        p["minutes"] += t.minutes
        p["overtime_minutes"] += t.overtime
        clients[t.client_id]["minutes"] += t.minutes
        day = days[t.day]
        day["minutes"] += t.minutes
        day["overtime_minutes"] += t.overtime
        if t.overtime or all_tasks:
            row = TaskRow(
                ticket_number=t.ticket_number,
                ticket_title=t.ticket_title,
                client=client_name(t.client_id),
                person=data.users[t.author_id].display_name,
                done_at=t.done_at,
                minutes=t.minutes,
                overtime_minutes=t.overtime,
            )
            if t.overtime:
                overtime_tasks.append(row)
            if all_tasks:
                task_rows.append(row)
    for ticket in data.opened:
        clients[ticket.client_id]["tickets_opened"] += 1
    for ticket in data.closed:
        clients[ticket.client_id]["tickets_closed"] += 1
        for user_id in ticket.people:
            people[user_id]["tickets_closed"] += 1

    person_rows = [
        PersonRow(
            id=data.users[user_id].public_id,
            name=data.users[user_id].display_name,
            minutes=s["minutes"],
            overtime_minutes=s["overtime_minutes"],
            tasks=s["tasks"],
            tickets_closed=s["tickets_closed"],
        )
        for user_id, s in people.items()
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
            minutes=sum(t.minutes for t in data.tasks),
            overtime_minutes=sum(t.overtime for t in data.tasks),
            tasks=len(data.tasks),
            tickets_opened=len(data.opened),
            tickets_closed=len(data.closed),
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
