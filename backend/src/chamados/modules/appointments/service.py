"""Regras da agenda. Cada pessoa vê os compromissos em que participa (o dono também participa) e
só o dono altera ou remove. O chamado ligado passa pela visibilidade: só se liga um chamado que
a pessoa vê, e o título só aparece para quem também o vê (ARCHITECTURE 9, regra 1).

O aviso (a bolinha no menu) acende 15 minutos antes do início e apaga quando a pessoa abre a
agenda ou quando o compromisso termina. Compromissos do dia inteiro não avisam.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from fastapi import HTTPException
from sqlalchemy import and_, delete, exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from chamados.core.permissions import CLIENT_ROLE
from chamados.core.timezone import LOCAL_TZ
from chamados.modules.appointments.models import Appointment, AppointmentAttendee
from chamados.modules.identity.deps import Auth
from chamados.modules.identity.models import User
from chamados.modules.organization.models import Role
from chamados.modules.tickets import service as tickets_service
from chamados.modules.tickets.models import Ticket
from chamados.modules.tickets.visibility import ticket_visibility_filter

ALERT_BEFORE = timedelta(minutes=15)


@dataclass
class AppointmentData:
    title: str
    starts_at: datetime
    ends_at: datetime
    all_day: bool = False
    description: str | None = None
    ticket_number: int | None = None
    attendee_ids: list[uuid.UUID] = field(default_factory=list)


@dataclass
class LinkedTicket:
    number: int
    # Vazio para quem não vê o chamado: só o número aparece.
    title: str | None


def all_day_period(first: date, last: date) -> tuple[datetime, datetime]:
    """Da meia-noite do primeiro dia à do dia seguinte ao último, no fuso da máquina."""
    return (
        datetime.combine(first, time(), LOCAL_TZ),
        datetime.combine(last + timedelta(days=1), time(), LOCAL_TZ),
    )


def _attends(user_id: int) -> ColumnElement[bool]:
    return exists().where(
        AppointmentAttendee.appointment_id == Appointment.id,
        AppointmentAttendee.user_id == user_id,
    )


async def between(
    db: AsyncSession, auth: Auth, start: datetime, end: datetime
) -> list[Appointment]:
    """Os compromissos da pessoa que tocam o período, pelo início."""
    rows = await db.scalars(
        select(Appointment)
        .where(_attends(auth.user.id), Appointment.starts_at < end, Appointment.ends_at > start)
        .order_by(Appointment.starts_at, Appointment.id)
    )
    return list(rows)


async def get(db: AsyncSession, auth: Auth, public_id: str) -> Appointment:
    """Compromisso de que a pessoa participa; o dos outros é 404, como o que não existe."""
    try:
        key = uuid.UUID(public_id)
    except ValueError:
        raise HTTPException(404, "Compromisso não encontrado.") from None
    found = await db.scalar(
        select(Appointment).where(Appointment.public_id == key, _attends(auth.user.id))
    )
    if found is None:
        raise HTTPException(404, "Compromisso não encontrado.")
    return found


async def linked_tickets(
    db: AsyncSession, auth: Auth, appointments: list[Appointment]
) -> dict[int, LinkedTicket]:
    """O chamado de cada compromisso (pelo id interno), com o título só se a pessoa o vê."""
    ids = {a.ticket_id for a in appointments if a.ticket_id}
    if not ids:
        return {}
    rows = await db.execute(
        select(Ticket.id, Ticket.number, Ticket.title, ticket_visibility_filter(auth.actor)).where(
            Ticket.id.in_(ids)
        )
    )
    return {
        id_: LinkedTicket(number, title if visible else None)
        for id_, number, title, visible in rows
    }


async def _attendees(db: AsyncSession, ids: list[uuid.UUID]) -> list[User]:
    """Colegas ativos (o papel Cliente não tem agenda)."""
    if not ids:
        return []
    users = list(
        await db.scalars(
            select(User)
            .join(Role, Role.id == User.role_id)
            .where(
                User.public_id.in_(set(ids)),
                User.is_active,
                User.deleted_at.is_(None),
                Role.code != CLIENT_ROLE,
            )
        )
    )
    if len(users) != len(set(ids)):
        raise HTTPException(422, "Participante inválido.")
    return users


async def _validated(db: AsyncSession, auth: Auth, data: AppointmentData) -> tuple[str, int | None]:
    title = data.title.strip()
    if not title:
        raise HTTPException(422, "Informe o título do compromisso.")
    if len(title) > 200:
        raise HTTPException(422, "O título pode ter até 200 caracteres.")
    if data.ends_at <= data.starts_at:
        raise HTTPException(422, "O fim do compromisso precisa ser depois do início.")
    ticket_id = None
    if data.ticket_number is not None:
        # Só um chamado que a pessoa vê (404 ou 403, como no detalhe).
        ticket_id = (await tickets_service.load(db, auth, str(data.ticket_number))).id
    return title, ticket_id


async def save(
    db: AsyncSession, auth: Auth, data: AppointmentData, appointment: Appointment | None = None
) -> Appointment:
    """Cria (sem `appointment`) ou altera um compromisso. Só o dono altera."""
    if appointment is not None and appointment.owner_id != auth.user.id:
        raise HTTPException(403, "Só quem criou o compromisso pode alterá-lo.")
    title, ticket_id = await _validated(db, auth, data)
    users = await _attendees(db, [i for i in data.attendee_ids if i != auth.user.public_id])
    if appointment is None:
        appointment = Appointment(owner_id=auth.user.id)
        db.add(appointment)
    appointment.title = title
    appointment.description = (data.description or "").strip() or None
    appointment.all_day = data.all_day
    appointment.ticket_id = ticket_id
    # O dono sempre participa; quem já estava fica com o aviso, a não ser que o horário mude.
    wanted = {auth.user.id, *(u.id for u in users)}
    current = {a.user_id: a for a in appointment.attendees}
    appointment.attendees = [
        current.get(user_id) or AppointmentAttendee(user_id=user_id) for user_id in wanted
    ]
    _set_period(appointment, data.starts_at, data.ends_at)
    await db.commit()
    return appointment


def _set_period(appointment: Appointment, starts_at: datetime, ends_at: datetime) -> None:
    """Novo horário: o aviso acende de novo para todos."""
    if (appointment.starts_at, appointment.ends_at) != (starts_at, ends_at):
        appointment.starts_at = starts_at
        appointment.ends_at = ends_at
        for attendee in appointment.attendees:
            attendee.alert_seen_at = None


async def reschedule(
    db: AsyncSession, auth: Auth, appointment: Appointment, starts_at: datetime, ends_at: datetime
) -> None:
    """Só o horário (arrastar as bordas na agenda). Só o dono altera."""
    if appointment.owner_id != auth.user.id:
        raise HTTPException(403, "Só quem criou o compromisso pode alterá-lo.")
    if ends_at <= starts_at:
        raise HTTPException(422, "O fim do compromisso precisa ser depois do início.")
    _set_period(appointment, starts_at, ends_at)
    await db.commit()


async def remove(db: AsyncSession, auth: Auth, appointment: Appointment) -> None:
    if appointment.owner_id != auth.user.id:
        raise HTTPException(403, "Só quem criou o compromisso pode removê-lo.")
    await db.execute(delete(Appointment).where(Appointment.id == appointment.id))
    await db.commit()


def _alerting(user_id: int, now: datetime) -> list[ColumnElement[bool]]:
    return [
        AppointmentAttendee.user_id == user_id,
        AppointmentAttendee.alert_seen_at.is_(None),
        AppointmentAttendee.appointment_id == Appointment.id,
        Appointment.all_day.is_(False),
        Appointment.starts_at <= now + ALERT_BEFORE,
        Appointment.ends_at > now,
    ]


async def alert_count(db: AsyncSession, auth: Auth, now: datetime) -> int:
    """Quantos compromissos estão com o aviso aceso (a bolinha do menu)."""
    return (
        await db.scalar(
            select(func.count())
            .select_from(AppointmentAttendee)
            .join(Appointment, and_(*_alerting(auth.user.id, now)))
        )
        or 0
    )


async def take_alerts(db: AsyncSession, auth: Auth, now: datetime) -> list[Appointment]:
    """Os compromissos com o aviso aceso, que se apaga: a pessoa abriu a agenda."""
    rows = list(
        await db.scalars(
            select(Appointment)
            .join(AppointmentAttendee, and_(*_alerting(auth.user.id, now)))
            .order_by(Appointment.starts_at, Appointment.id)
        )
    )
    if rows:
        await db.execute(
            update(AppointmentAttendee)
            .where(
                AppointmentAttendee.user_id == auth.user.id,
                AppointmentAttendee.appointment_id.in_([a.id for a in rows]),
            )
            .values(alert_seen_at=now)
        )
        await db.commit()
    return rows
