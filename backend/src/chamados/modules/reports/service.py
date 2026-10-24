"""Números dos relatórios (docs/14 §14.7): horas por pessoa, por cliente e por dia, e horas extras.

Tudo é calculado na hora, a partir das tarefas (`ticket_comments`) e dos chamados. Quem vê o quê:
admin e auditor (`report.view_all`) veem tudo; o supervisor, os chamados dos grupos que
supervisiona e o próprio trabalho; os demais, só o próprio trabalho. Em cima disso vale sempre o
filtro de visibilidade dos chamados (regra 1 da arquitetura).
"""

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import ColumnElement, and_, not_, or_, select, true
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from chamados.core.permissions import P, can
from chamados.core.timezone import LOCAL_TZ
from chamados.modules.catalog.models import TicketStatus
from chamados.modules.clients.models import Client
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
    holidays = set(wh.holidays)
    inside = timedelta()
    day = begin.astimezone(TZ).date()
    while day <= end.astimezone(TZ).date():
        if day.weekday() in wh.weekdays and day not in holidays:
            # Em UTC: somar e subtrair datas no mesmo fuso do zoneinfo ignora a troca de horário.
            w_start = datetime.combine(day, wh.start, TZ).astimezone(UTC)
            w_end = datetime.combine(day, wh.end, TZ).astimezone(UTC)
            overlap = min(end, w_end) - max(begin, w_start)
            if overlap > timedelta():
                inside += overlap
        day += timedelta(days=1)
    return minutes - round(inside.total_seconds() / 60)


async def options(db: AsyncSession, auth: Auth) -> ReportOptions:
    actor = auth.actor
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
    clients = sorted(await db.scalars(select(Client)), key=lambda c: c.label.casefold())
    return ReportOptions(
        teams=[
            Ref(id=t.public_id, name=t.name) for t in await db.scalars(teams.order_by(Team.name))
        ],
        people=[
            Ref(id=u.public_id, name=u.display_name)
            for u in await db.scalars(people.order_by(User.display_name))
        ],
        clients=[Ref(id=c.public_id, name=c.label) for c in clients],
        statuses=[
            StatusRef(id=s.id, name=s.name)
            for s in await db.scalars(select(TicketStatus).order_by(TicketStatus.sort_order))
        ],
    )


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


@dataclass
class Facts:
    """Os dados de um período, já com o escopo e os filtros, e os nomes do que aparece neles."""

    work_hours: WorkHours
    tasks: list[TaskFact]
    opened: list[TicketFact]
    closed: list[TicketFact]
    canceled: list[TicketFact]
    backlog: list[TicketFact]
    users: dict[int, User]
    clients: dict[int, Client]
    teams: dict[int, Team]
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


async def facts(db: AsyncSession, auth: Auth, f: Filters) -> Facts:
    wh = await get_work_hours(db)
    since, until = _bounds(f)
    me = auth.user.id
    people_ids = {p.id for p in f.people}

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
    # Só as colunas usadas: a tarefa inteira traria o texto (até 50 mil caracteres) e o autor
    # de cada linha; os nomes vêm depois, uma vez cada.
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

    async def tickets(*conds: ColumnElement[bool]) -> Sequence[Any]:
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
            )
            .join(TicketStatus, TicketStatus.id == Ticket.status_id)
            .where(*ticket_conds, *conds)
            .order_by(Ticket.number)
        )
        return (await db.execute(query)).all()

    opened = await tickets(Ticket.created_at >= since, Ticket.created_at < until)
    closed = await tickets(
        TicketStatus.kind == "closed", Ticket.closed_at >= since, Ticket.closed_at < until
    )
    canceled = await tickets(
        TicketStatus.kind == "canceled", Ticket.canceled_at >= since, Ticket.canceled_at < until
    )
    # Em aberto no fim: registrados até lá e não concluídos nem cancelados antes dele (pelas
    # datas de conclusão e cancelamento, as mesmas das medidas). O status de então é o "de" da
    # primeira mudança depois do fim; sem mudança, o atual.
    candidates = await tickets(
        Ticket.created_at < until,
        not_(and_(TicketStatus.kind == "closed", Ticket.closed_at < until)),
        not_(and_(TicketStatus.kind == "canceled", Ticket.canceled_at < until)),
    )
    statuses = {s.id: s for s in await db.scalars(select(TicketStatus))}
    kinds = {i: s.kind for i, s in statuses.items()}
    status_at_end: dict[int, int] = {}
    if candidates:
        first_change = await db.execute(
            select(TicketEvent.ticket_id, TicketEvent.payload["from"]["id"].as_integer())
            .where(
                TicketEvent.event_type == "ticket.status_changed",
                TicketEvent.created_at >= until,
                TicketEvent.ticket_id.in_([r.id for r in candidates]),
            )
            .ext(distinct_on(TicketEvent.ticket_id))
            .order_by(TicketEvent.ticket_id, TicketEvent.created_at)
        )
        status_at_end = {ticket_id: status_id for ticket_id, status_id in first_change}
    backlog = [
        r for r in candidates if kinds.get(status_at_end.get(r.id, r.status_id)) not in FINAL
    ]

    # As mudanças de status dos concluídos, para o tempo líquido.
    changes: dict[int, list[tuple[datetime, int, int]]] = defaultdict(list)
    if closed:
        events = await db.execute(
            select(
                TicketEvent.ticket_id,
                TicketEvent.created_at,
                TicketEvent.payload["from"]["id"].as_integer(),
                TicketEvent.payload["to"]["id"].as_integer(),
            )
            .where(
                TicketEvent.event_type == "ticket.status_changed",
                TicketEvent.ticket_id.in_([r.id for r in closed]),
            )
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
                TicketCoAssignee.ticket_id.in_(list(assignees))
            )
        )
        for ticket_id, user_id in co:
            assignees[ticket_id].add(user_id)
    allowed: set[int] | None = None
    if people_ids:
        allowed = people_ids
    elif not can(auth.actor, P.REPORT_VIEW_ALL):
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
            net_lead=net_minutes(r.created_at, r.closed_at, changes[r.id], kinds),
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
        work_hours=wh,
        tasks=tasks,
        opened=opened_facts,
        closed=closed_facts,
        canceled=canceled_facts,
        backlog=backlog_facts,
        users={u.id: u for u in await db.scalars(select(User).where(User.id.in_(user_ids)))},
        clients={
            c.id: c for c in await db.scalars(select(Client).where(Client.id.in_(client_ids)))
        },
        teams={t.id: t for t in await db.scalars(select(Team).where(Team.id.in_(team_ids)))},
        statuses=statuses,
    )


async def build(db: AsyncSession, auth: Auth, f: Filters, *, all_tasks: bool = False) -> Report:
    """Os números das telas prontas, da API e do PDF. `all_tasks`: também a lista de todas as
    tarefas (`Report.tasks`, para o CSV)."""
    data = await facts(db, auth, f)
    people: dict[int, PersonRow] = {}
    clients: dict[int | None, ClientRow] = {}
    days = {
        f.start + timedelta(days=i): DayRow(
            date=f.start + timedelta(days=i), minutes=0, overtime_minutes=0
        )
        for i in range((f.end - f.start).days + 1)
    }
    overtime_tasks: list[TaskRow] = []
    task_rows: list[TaskRow] = []

    def person_row(user_id: int) -> PersonRow:
        if user_id not in people:
            user = data.users[user_id]
            people[user_id] = PersonRow(
                id=user.public_id,
                name=user.display_name,
                minutes=0,
                overtime_minutes=0,
                tasks=0,
                tickets_closed=0,
            )
        return people[user_id]

    def client_row(client_id: int | None) -> ClientRow:
        if client_id not in clients:
            client = data.clients.get(client_id) if client_id is not None else None
            clients[client_id] = ClientRow(
                id=client.public_id if client else None,
                name=client.label if client else None,
                minutes=0,
                tickets_opened=0,
                tickets_closed=0,
            )
        return clients[client_id]

    for t in data.tasks:
        p = person_row(t.author_id)
        p.tasks += 1
        p.minutes += t.minutes
        p.overtime_minutes += t.overtime
        client = client_row(t.client_id)
        client.minutes += t.minutes
        day = days[t.day]
        day.minutes += t.minutes
        day.overtime_minutes += t.overtime
        if t.overtime or all_tasks:
            row = TaskRow(
                ticket_number=t.ticket_number,
                ticket_title=t.ticket_title,
                client=client.name,
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
        client_row(ticket.client_id).tickets_opened += 1
    for ticket in data.closed:
        client_row(ticket.client_id).tickets_closed += 1
        for user_id in ticket.people:
            person_row(user_id).tickets_closed += 1

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
        people=sorted(people.values(), key=lambda p: (-p.minutes, p.name)),
        clients=sorted(
            clients.values(),
            key=lambda c: (-c.minutes, -c.tickets_opened, c.name is None, c.name or ""),
        ),
        days=list(days.values()),
        overtime_tasks=overtime_tasks,
        tasks=task_rows,
    )
