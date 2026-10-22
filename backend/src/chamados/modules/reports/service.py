"""Números dos relatórios (docs/14 §14.7): horas por pessoa, por cliente e por dia, e horas extras.

Tudo é calculado na hora, a partir das tarefas (`ticket_comments`) e dos chamados. Quem vê o quê:
admin e auditor (`report.view_all`) veem tudo; o supervisor, os chamados dos grupos que
supervisiona e o próprio trabalho; os demais, só o próprio trabalho. Em cima disso vale sempre o
filtro de visibilidade dos chamados (regra 1 da arquitetura).
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import ColumnElement, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from chamados.core.permissions import P, can
from chamados.modules.catalog.models import TicketStatus
from chamados.modules.clients.models import Client
from chamados.modules.identity.deps import Auth
from chamados.modules.identity.models import User
from chamados.modules.organization.models import Team, TeamMember
from chamados.modules.reports.schemas import (
    ClientRow,
    DayRow,
    OvertimeTask,
    PersonRow,
    Ref,
    Report,
    ReportOptions,
    Totals,
)
from chamados.modules.system.work_hours import WorkHours, get_work_hours
from chamados.modules.tickets.models import Ticket, TicketCoAssignee, TicketComment
from chamados.modules.tickets.visibility import assigned_to, ticket_visibility_filter

TZ = ZoneInfo("America/Sao_Paulo")
MAX_DAYS = 366


@dataclass
class Filters:
    start: date
    end: date  # inclusive
    team: Team | None = None
    person: User | None = None
    client: Client | None = None


def outside_minutes(end: datetime, minutes: int, wh: WorkHours) -> int:
    """Minutos da tarefa fora do expediente. A tarefa vai de `end - minutes` até `end` (done_at
    é quando ela terminou), no horário de São Paulo."""
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
    return ReportOptions(
        teams=[
            Ref(id=t.public_id, name=t.name) for t in await db.scalars(teams.order_by(Team.name))
        ],
        people=[
            Ref(id=u.public_id, name=u.display_name)
            for u in await db.scalars(people.order_by(User.display_name))
        ],
    )


async def resolve(
    db: AsyncSession,
    auth: Auth,
    *,
    start: date,
    end: date,
    team: uuid.UUID | None,
    person: uuid.UUID | None,
    client: uuid.UUID | None,
) -> Filters:
    """Confere o período e as escolhas dos filtros contra o que a pessoa pode ver."""
    if end < start:
        raise HTTPException(422, "O período precisa terminar depois de começar.")
    if (end - start).days >= MAX_DAYS:
        raise HTTPException(422, "O período pode ter no máximo 366 dias.")
    if end == date.max:  # o fim do período é o começo do dia seguinte (_bounds)
        raise HTTPException(422, "Data inválida.")
    f = Filters(start=start, end=end)
    if team:
        f.team = await db.scalar(select(Team).where(Team.public_id == team))
        if f.team is None:
            raise HTTPException(404, "Grupo não encontrado.")
    if person:
        f.person = await db.scalar(select(User).where(User.public_id == person))
        if f.person is None:
            raise HTTPException(404, "Usuário não encontrado.")
    if client:
        f.client = await db.scalar(select(Client).where(Client.public_id == client))
        if f.client is None:
            raise HTTPException(404, "Cliente não encontrado.")

    actor = auth.actor
    if not can(actor, P.REPORT_VIEW_ALL):
        if f.team and f.team.id not in actor.supervises:
            raise HTTPException(403, "Você não tem permissão para esta ação.")
        if f.person and f.person.id != actor.user_id:
            supervised = await db.scalar(
                select(TeamMember.user_id).where(
                    TeamMember.user_id == f.person.id, TeamMember.team_id.in_(actor.supervises)
                )
            )
            if supervised is None:
                raise HTTPException(403, "Você só pode ver os seus próprios números.")
    return f


def _bounds(f: Filters) -> tuple[datetime, datetime]:
    return (
        datetime.combine(f.start, time(), TZ),
        datetime.combine(f.end + timedelta(days=1), time(), TZ),
    )


def _ticket_filters(auth: Auth, f: Filters) -> list[ColumnElement[bool]]:
    conds = [ticket_visibility_filter(auth.actor)]
    if f.team:
        conds.append(Ticket.team_id == f.team.id)
    if f.client:
        conds.append(Ticket.client_id == f.client.id)
    return conds


def _own_or_supervised(auth: Auth, own: ColumnElement[bool]) -> ColumnElement[bool]:
    actor = auth.actor
    if can(actor, P.REPORT_VIEW_ALL):
        return true()
    return or_(own, Ticket.team_id.in_(actor.supervises))


async def build(db: AsyncSession, auth: Auth, f: Filters) -> Report:
    wh = await get_work_hours(db)
    since, until = _bounds(f)
    me = auth.user.id

    # --- tarefas do período (horas, horas extras) ---
    task_conds = [
        *_ticket_filters(auth, f),
        _own_or_supervised(auth, TicketComment.author_id == me),
        TicketComment.deleted_at.is_(None),
        TicketComment.done_at >= since,
        TicketComment.done_at < until,
    ]
    if f.person:
        task_conds.append(TicketComment.author_id == f.person.id)
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
    overtime_tasks: list[OvertimeTask] = []

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
        if extra:
            overtime_tasks.append(
                OvertimeTask(
                    ticket_number=number,
                    ticket_title=title,
                    person=author.display_name,
                    done_at=done_at,
                    minutes=minutes,
                    overtime_minutes=extra,
                )
            )

    # --- chamados registrados e concluídos no período ---
    ticket_conds = [*_ticket_filters(auth, f), _own_or_supervised(auth, assigned_to(me))]
    if f.person:
        ticket_conds.append(assigned_to(f.person.id))
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
    if f.person:
        closers = {u: n for u, n in closers.items() if u == f.person.id}
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
    )
