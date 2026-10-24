"""Números dos relatórios (docs/14 §14.7): horas por pessoa, por cliente e por dia, e horas extras.

Tudo é calculado na hora, a partir das tarefas (`ticket_comments`) e dos chamados. Quem vê o quê:
admin e auditor (`report.view_all`) veem tudo; o supervisor, os chamados dos grupos que
supervisiona e o próprio trabalho; os demais, só o próprio trabalho. Em cima disso vale sempre o
filtro de visibilidade dos chamados (regra 1 da arquitetura).
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

from fastapi import HTTPException
from sqlalchemy import ColumnElement, func, or_, select, true
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
from chamados.modules.tickets.models import Ticket, TicketCoAssignee, TicketComment
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


async def build(db: AsyncSession, auth: Auth, f: Filters, *, all_tasks: bool = False) -> Report:
    """`all_tasks`: também a lista de todas as tarefas (`Report.tasks`, para o CSV)."""
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
    # de cada linha; os autores vêm depois, uma vez cada.
    tasks = (
        await db.execute(
            select(
                TicketComment.author_id,
                TicketComment.time_spent_minutes,
                TicketComment.done_at,
                Ticket.number,
                Ticket.title,
                Ticket.client_id,
            )
            .join(Ticket, Ticket.id == TicketComment.ticket_id)
            .where(*task_conds)
            .order_by(TicketComment.done_at)
        )
    ).all()
    authors = {
        u.id: u
        for u in await db.scalars(select(User).where(User.id.in_({t.author_id for t in tasks})))
    }

    people: dict[int, PersonRow] = {}
    clients: dict[int | None, ClientRow] = {}
    client_ids: set[int] = set()
    days = {
        f.start + timedelta(days=i): DayRow(
            date=f.start + timedelta(days=i), minutes=0, overtime_minutes=0
        )
        for i in range((f.end - f.start).days + 1)
    }
    overtime_tasks: list[TaskRow] = []
    task_rows: list[TaskRow] = []
    row_clients: list[tuple[TaskRow, int | None]] = []  # o nome do cliente vem no fim

    def person_row(user: User) -> PersonRow:
        if user.id not in people:
            people[user.id] = PersonRow(
                id=user.public_id,
                name=user.display_name,
                minutes=0,
                overtime_minutes=0,
                tasks=0,
                tickets_closed=0,
            )
        return people[user.id]

    def client_row(client_id: int | None) -> ClientRow:
        if client_id not in clients:
            clients[client_id] = ClientRow(
                id=None, name=None, minutes=0, tickets_opened=0, tickets_closed=0
            )
            if client_id is not None:
                client_ids.add(client_id)
        return clients[client_id]

    for author_id, time_spent, done_at, number, title, client_id in tasks:
        minutes = time_spent or 0
        extra = outside_minutes(done_at, minutes, wh) if minutes else 0
        author = authors[author_id]
        p = person_row(author)
        p.tasks += 1
        p.minutes += minutes
        p.overtime_minutes += extra
        client_row(client_id).minutes += minutes
        day = days[done_at.astimezone(TZ).date()]
        day.minutes += minutes
        day.overtime_minutes += extra
        if extra or all_tasks:
            row = TaskRow(
                ticket_number=number,
                ticket_title=title,
                client=None,
                person=author.display_name,
                done_at=done_at,
                minutes=minutes,
                overtime_minutes=extra,
            )
            row_clients.append((row, client_id))
            if extra:
                overtime_tasks.append(row)
            if all_tasks:
                task_rows.append(row)

    # --- chamados registrados e concluídos no período ---
    ticket_conds = [*_ticket_filters(auth, f), _own_or_supervised(auth, assigned_to(me))]
    if people_ids:
        ticket_conds.append(or_(*(assigned_to(i) for i in people_ids)))
    opened = await db.execute(
        select(Ticket.client_id, func.count())
        .where(*ticket_conds, Ticket.created_at >= since, Ticket.created_at < until)
        .group_by(Ticket.client_id)
    )
    tickets_opened = 0
    for client_id, count in opened:
        client_row(client_id).tickets_opened += count
        tickets_opened += count

    closed = (
        await db.execute(
            select(Ticket.id, Ticket.client_id, Ticket.assignee_id)
            .join(TicketStatus, TicketStatus.id == Ticket.status_id)
            .where(
                *ticket_conds,
                TicketStatus.kind == "closed",
                Ticket.closed_at >= since,
                Ticket.closed_at < until,
            )
        )
    ).all()
    for _, client_id, _ in closed:
        client_row(client_id).tickets_closed += 1
    # Concluídos por pessoa: cada responsável (principal ou não) conta o chamado.
    assignees: dict[int, set[int]] = defaultdict(set)
    for ticket_id, _, assignee_id in closed:
        if assignee_id:
            assignees[ticket_id].add(assignee_id)
    if closed:
        co = await db.execute(
            select(TicketCoAssignee.ticket_id, TicketCoAssignee.user_id).where(
                TicketCoAssignee.ticket_id.in_([t for t, _, _ in closed])
            )
        )
        for ticket_id, user_id in co:
            assignees[ticket_id].add(user_id)
    closers: dict[int, int] = defaultdict(int)
    for users in assignees.values():
        for user_id in users:
            closers[user_id] += 1
    if people_ids:
        closers = {u: n for u, n in closers.items() if u in people_ids}
    elif not can(auth.actor, P.REPORT_VIEW_ALL):
        # Um colega de outro grupo pode ser corresponsável: só entra quem a pessoa pode ver.
        allowed = {me} | set(
            await db.scalars(
                select(TeamMember.user_id).where(TeamMember.team_id.in_(auth.actor.supervises))
            )
        )
        closers = {u: n for u, n in closers.items() if u in allowed}
    for user in await db.scalars(select(User).where(User.id.in_(closers))):
        person_row(user).tickets_closed += closers[user.id]

    # --- nomes dos clientes ---
    for c in await db.scalars(select(Client).where(Client.id.in_(client_ids))):
        clients[c.id].id = c.public_id
        clients[c.id].name = c.label
    for row, client_id in row_clients:
        row.client = clients[client_id].name

    return Report(
        start=f.start,
        end=f.end,
        work_hours=wh,
        totals=Totals(
            minutes=sum(p.minutes for p in people.values()),
            overtime_minutes=sum(p.overtime_minutes for p in people.values()),
            tasks=len(tasks),
            tickets_opened=tickets_opened,
            tickets_closed=len(closed),
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
