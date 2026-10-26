"""Quem recebe o quê (docs/10 §10.10): cada evento do outbox vira um e-mail por pessoa.

Na Fase 1 (sem o sino), os eventos marcados só com 🔔 também vão por e-mail. Quem causou o evento
não recebe, e quem está inativo, foi excluído ou não tem e-mail fica de fora. Cada pessoa recebe um
e-mail só por ação: vale o primeiro motivo da lista do handler (menção, atribuição, o resto).
"""

import uuid
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from chamados.config import Settings
from chamados.modules.catalog.models import TicketStatus
from chamados.modules.identity.models import User
from chamados.modules.jobs.models import OutboxEvent
from chamados.modules.jobs.service import Handler, enqueue
from chamados.modules.notifications import messages
from chamados.modules.organization.models import Team, TeamMember
from chamados.modules.system.service import user_locale
from chamados.modules.tickets.models import Ticket, TicketComment

Recipients = Sequence[tuple[str, Iterable[User]]]  # (motivo, pessoas), na ordem de prioridade


async def _users(db: AsyncSession, refs: Iterable[str | dict[str, Any] | None]) -> list[User]:
    """Usuários pelas referências do payload: o public_id ou `{"id", "name"}`."""
    ids = {uuid.UUID(r["id"] if isinstance(r, dict) else r) for r in refs if r}
    if not ids:
        return []
    return list((await db.scalars(select(User).where(User.public_id.in_(ids)))).all())


async def _team_members(db: AsyncSession, team_ref: dict[str, Any]) -> list[User]:
    return list(
        (
            await db.scalars(
                select(User)
                .join(TeamMember, TeamMember.user_id == User.id)
                .join(Team, Team.id == TeamMember.team_id)
                .where(Team.public_id == uuid.UUID(team_ref["id"]))
            )
        ).all()
    )


def _assignees(ticket: Ticket) -> list[User]:
    return [ticket.assignee, *(c.user for c in ticket.co_assignees)]


def _watchers(ticket: Ticket) -> list[User]:
    return [w.user for w in ticket.watchers]


async def _send(
    db: AsyncSession,
    settings: Settings,
    event: OutboxEvent,
    ticket: Ticket,
    recipients: Recipients,
    *,
    group: str = "",
) -> None:
    actor_id = event.payload["actor_user_id"]
    chosen: dict[int, tuple[User, str, str]] = {}
    for reason, users in recipients:
        for user in users:
            if user.id != actor_id and user.is_active and user.deleted_at is None and user.email:
                chosen.setdefault(user.id, (user, user.email, reason))
    if not chosen:
        return
    actor = await db.get(User, actor_id)
    comment = None
    if comment_id := event.payload["data"].get("comment_id"):
        comment = await db.scalar(
            select(TicketComment.body).where(
                TicketComment.public_id == uuid.UUID(comment_id),
                TicketComment.deleted_at.is_(None),
            )
        )
    for user, email, reason in chosen.values():
        subject, body = messages.render(
            await user_locale(db, user),
            reason,
            nome=user.display_name.split()[0],
            quem=actor.display_name if actor else "",
            numero=ticket.number,
            titulo=ticket.title,
            grupo=group,
            # Como nos links de convite: APP_BASE_URL pode vir com a "/" do fim.
            url=f"{settings.app_base_url.rstrip('/')}/chamados/{ticket.number}",
            comentario=comment,
        )
        enqueue(db, "notifications.send_email", to=email, subject=subject, body=body)


async def _ticket(db: AsyncSession, event: OutboxEvent) -> Ticket:
    return (
        await db.scalars(
            select(Ticket)
            .where(Ticket.id == event.payload["ticket_id"])
            .options(selectinload(Ticket.watchers), selectinload(Ticket.co_assignees))
        )
    ).one()


async def ticket_created(db: AsyncSession, settings: Settings, event: OutboxEvent) -> None:
    ticket = await _ticket(db, event)
    data = event.payload["data"]
    recipients: list[tuple[str, Iterable[User]]] = [
        ("mentioned", await _users(db, event.payload.get("mention_ids", []))),
        ("assigned", await _users(db, [data["assignee"], *data.get("co_assignees", [])])),
    ]
    # O grupo é avisado conforme a configuração dele (docs/10 §10.4).
    if ticket.team.notify_on_new == "email_all_members":
        recipients.append(("new_in_team", await _team_members(db, data["team"])))
    await _send(db, settings, event, ticket, recipients, group=data["team"]["name"])


async def ticket_assigned(db: AsyncSession, settings: Settings, event: OutboxEvent) -> None:
    to = await _users(db, [event.payload["data"]["to"]])
    await _send(db, settings, event, await _ticket(db, event), [("assigned", to)])


async def assignees_changed(db: AsyncSession, settings: Settings, event: OutboxEvent) -> None:
    added = await _users(db, event.payload["data"]["added"])
    await _send(db, settings, event, await _ticket(db, event), [("assigned", added)])


async def ticket_transferred(db: AsyncSession, settings: Settings, event: OutboxEvent) -> None:
    data = event.payload["data"]
    recipients = [
        ("assigned", await _users(db, [data["assignee"]["to"]])),
        ("transferred", await _team_members(db, data["to"])),
    ]
    await _send(db, settings, event, await _ticket(db, event), recipients, group=data["to"]["name"])


async def status_changed(db: AsyncSession, settings: Settings, event: OutboxEvent) -> None:
    """Concluído (entrando num status `closed`) e reaberto (saindo de um, menos para cancelado); os
    demais, só para quem foi mencionado no comentário da mudança."""
    ticket = await _ticket(db, event)
    data = event.payload["data"]
    rows = await db.execute(
        select(TicketStatus.id, TicketStatus.kind).where(
            TicketStatus.id.in_([data["from"]["id"], data["to"]["id"]])
        )
    )
    kinds = {status_id: kind for status_id, kind in rows}
    before, after = kinds.get(data["from"]["id"]), kinds.get(data["to"]["id"])
    recipients: list[tuple[str, Iterable[User]]] = [
        ("mentioned", await _users(db, event.payload.get("mention_ids", [])))
    ]
    if after == "closed" and before != "closed":
        recipients.append(("closed", [*_watchers(ticket), ticket.created_by]))
    elif before == "closed" and after not in ("closed", "canceled"):
        recipients.append(("reopened", [*_assignees(ticket), *_watchers(ticket)]))
    await _send(db, settings, event, ticket, recipients)


async def comment_created(db: AsyncSession, settings: Settings, event: OutboxEvent) -> None:
    ticket = await _ticket(db, event)
    recipients = [
        ("mentioned", await _users(db, event.payload.get("mention_ids", []))),
        ("comment", [*_assignees(ticket), *_watchers(ticket)]),
    ]
    await _send(db, settings, event, ticket, recipients)


HANDLERS: dict[str, Handler] = {
    "ticket.created": ticket_created,
    "ticket.assigned": ticket_assigned,
    "ticket.assignees_changed": assignees_changed,
    "ticket.transferred": ticket_transferred,
    "ticket.status_changed": status_changed,
    "comment.created": comment_created,
}
