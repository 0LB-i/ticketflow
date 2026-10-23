"""Leituras dos chamados já montadas nos schemas de saída: o que a API, as telas do servidor e
outros consumidores (integrações, MCP) devolvem. Sem objetos HTTP de resposta: quem chama decide o
formato. A visibilidade e as ações vêm do `service`.
"""

import uuid
from collections.abc import Sequence

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chamados.modules.attachments import service as attachments
from chamados.modules.audit.service import record
from chamados.modules.identity.deps import Auth
from chamados.modules.identity.models import User
from chamados.modules.tickets import service
from chamados.modules.tickets.models import Ticket, TicketComment, TicketEvent
from chamados.modules.tickets.schemas import (
    CategoryRef,
    CommentList,
    CommentOut,
    EventList,
    EventOut,
    PersonTime,
    ResolutionRef,
    StatusRef,
    TicketListItem,
    TicketOut,
    TicketPage,
    TicketSummary,
    TicketView,
    UserRef,
    WatcherOut,
)
from chamados.modules.tickets.schemas import Ref as RefOut
from chamados.modules.tickets.visibility import SEE_EVERYTHING, sees_without_privilege


def _user(u: User | None) -> UserRef | None:
    return UserRef(id=u.public_id, display_name=u.display_name) if u else None


def _summary(t: Ticket, paths: dict[int, str]) -> TicketSummary:
    return TicketSummary(
        id=t.public_id,
        number=t.number,
        title=t.title,
        type=t.type,
        status=StatusRef(id=t.status.id, name=t.status.name, kind=t.status.kind),
        team=RefOut(id=t.team.public_id, name=t.team.name),
        category=CategoryRef(
            id=t.category.public_id, name=t.category.name, path=paths[t.category.id]
        )
        if t.category
        else None,
        client=RefOut(id=t.client.public_id, name=t.client.label) if t.client else None,
        beneficiary_name=t.beneficiary_name,
        assignee=UserRef(id=t.assignee.public_id, display_name=t.assignee.display_name),
        started_at=t.started_at,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


async def list_page(
    db: AsyncSession,
    auth: Auth,
    *,
    view: TicketView,
    team: uuid.UUID | None,
    assignee: str | None,
    kinds: Sequence[str],
    q: str | None,
    limit: int,
    cursor: str | None,
) -> TicketPage:
    """Uma página da lista (fila e filtros como em `service.list_tickets`)."""
    rows, next_cursor = await service.list_tickets(
        db,
        auth,
        view=view,
        team=team,
        assignee=assignee,
        kinds=kinds,
        q=q,
        limit=limit,
        cursor=cursor,
    )
    paths = await service.category_paths(db, [t for t, _, _ in rows])
    return TicketPage(
        items=[
            TicketListItem(**dict(_summary(t, paths)), has_news=news, time_spent_minutes=minutes)
            for t, news, minutes in rows
        ],
        next_cursor=next_cursor,
    )


async def detail(db: AsyncSession, auth: Auth, t: Ticket) -> TicketOut:
    paths = await service.category_paths(db, [t])
    times = [
        PersonTime(id=u.public_id, display_name=u.display_name, minutes=m)
        for u, m in await service.time_by_person(db, t)
    ]
    return TicketOut(
        **dict(_summary(t, paths)),
        description=t.description,
        created_by=_user(t.created_by),
        resolution_code=ResolutionRef(id=t.resolution_code.id, name=t.resolution_code.name)
        if t.resolution_code
        else None,
        reopened_count=t.reopened_count,
        closed_at=t.closed_at,
        co_assignees=[
            UserRef(id=c.user.public_id, display_name=c.user.display_name) for c in t.co_assignees
        ],
        watchers=[
            WatcherOut(id=w.user.public_id, display_name=w.user.display_name, kind=w.kind)
            for w in t.watchers
        ],
        attachments=await attachments.of_ticket(db, t.id),
        time_spent_minutes=sum(p.minutes for p in times),
        time_by_person=times,
        etag=service.etag(t),
        allowed_actions=sorted(service.actions(auth, t)),
    )


async def load_detail(db: AsyncSession, auth: Auth, ticket_ref: str) -> TicketOut:
    """O detalhe relido do banco, sem marcar a visita nem auditar o acesso (depois de uma
    alteração, e nos trechos das telas do servidor)."""
    return await detail(db, auth, await service.load(db, auth, ticket_ref))


async def open_ticket(
    db: AsyncSession, auth: Auth, ticket: Ticket, request: Request | None = None
) -> TicketOut:
    """A abertura do detalhe (já carregado com `service.load`): audita o acesso a confidencial,
    guarda a visita e monta o detalhe. `request` só dá o IP e o navegador à auditoria."""
    await audit_confidential(db, auth, ticket, request)
    await service.mark_read(db, auth, ticket)
    return await detail(db, auth, ticket)


async def audit_confidential(
    db: AsyncSession, auth: Auth, ticket: Ticket, request: Request | None = None
) -> None:
    """Regra 6 do docs/08 §8.4: admin e auditor leem confidenciais, e isso fica na auditoria."""
    if (
        ticket.category
        and ticket.category.is_confidential
        and auth.actor.role in SEE_EVERYTHING
        and not sees_without_privilege(auth.actor, ticket)
    ):
        record(
            db,
            "ticket.confidential_viewed",
            request=request,
            actor_user_id=auth.user.id,
            target_type="ticket",
            target_id=ticket.public_id,
        )
        await db.commit()


def comment_out(c: TicketComment) -> CommentOut:
    return CommentOut(
        id=c.public_id,
        author=_user(c.author),
        body=c.body,
        is_solution=c.is_solution,
        time_spent_minutes=c.time_spent_minutes,
        done_at=c.done_at,
        created_at=c.created_at,
        edited_at=c.edited_at,
    )


async def comments(db: AsyncSession, ticket: Ticket) -> CommentList:
    """As tarefas (não removidas) de um chamado já carregado com `service.load`."""
    rows = await db.scalars(
        select(TicketComment)
        .where(TicketComment.ticket_id == ticket.id, TicketComment.deleted_at.is_(None))
        .order_by(TicketComment.done_at, TicketComment.id)
    )
    return CommentList(items=[comment_out(c) for c in rows])


async def events(db: AsyncSession, ticket: Ticket) -> EventList:
    """O histórico de um chamado já carregado com `service.load`."""
    rows = await db.scalars(
        select(TicketEvent)
        .where(TicketEvent.ticket_id == ticket.id)
        .order_by(TicketEvent.created_at, TicketEvent.id)
    )
    return EventList(
        items=[
            EventOut(
                id=e.id,
                type=e.event_type,
                actor=_user(e.actor),
                payload=e.payload,
                created_at=e.created_at,
            )
            for e in rows
        ]
    )
