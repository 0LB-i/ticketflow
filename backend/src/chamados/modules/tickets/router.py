"""API dos chamados (docs/05). O chamado é aceito pelo número ou pelo UUID."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chamados.db.session import DB
from chamados.modules.attachments import service as attachments
from chamados.modules.audit.service import record
from chamados.modules.identity.deps import Auth, CurrentAuth
from chamados.modules.identity.models import User
from chamados.modules.tickets import service
from chamados.modules.tickets.models import Ticket, TicketComment, TicketEvent
from chamados.modules.tickets.schemas import (
    AssignIn,
    CategoryRef,
    CommentIn,
    CommentList,
    CommentOut,
    EventList,
    EventOut,
    NextIn,
    ResolutionRef,
    StatusKind,
    StatusRef,
    TicketCounts,
    TicketCreate,
    TicketListItem,
    TicketOut,
    TicketPage,
    TicketSummary,
    TicketUpdate,
    TicketView,
    TransferIn,
    TransitionIn,
    UserRef,
    WatcherOut,
)
from chamados.modules.tickets.schemas import Ref as RefOut
from chamados.modules.tickets.visibility import SEE_EVERYTHING, sees_without_privilege

router = APIRouter(prefix="/tickets", tags=["chamados"])


def _user(u: User | None) -> UserRef | None:
    return UserRef(id=u.public_id, full_name=u.full_name) if u else None


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
        department=RefOut(id=t.department.public_id, name=t.department.name)
        if t.department
        else None,
        client=RefOut(id=t.client.public_id, name=t.client.name) if t.client else None,
        beneficiary_name=t.beneficiary_name,
        assignee=_user(t.assignee),
        started_at=t.started_at,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


async def _detail(db: AsyncSession, auth: Auth, t: Ticket) -> TicketOut:
    paths = await service.category_paths(db)
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
            UserRef(id=c.user.public_id, full_name=c.user.full_name) for c in t.co_assignees
        ],
        watchers=[
            WatcherOut(id=w.user.public_id, full_name=w.user.full_name, kind=w.kind)
            for w in t.watchers
        ],
        attachments=await attachments.of_ticket(db, t.id),
        allowed_actions=sorted(service.actions(auth, t)),
    )


def _comment_out(c: TicketComment) -> CommentOut:
    return CommentOut(
        id=c.public_id,
        author=_user(c.author),
        body=c.body,
        is_solution=c.is_solution,
        created_at=c.created_at,
        edited_at=c.edited_at,
        editable_until=c.created_at + service.COMMENT_EDIT_WINDOW,
    )


@router.get("", response_model=TicketPage)
async def list_tickets(
    auth: CurrentAuth,
    db: DB,
    view: Annotated[TicketView, Query(description="fila (aba da lista)")] = "all",
    team: Annotated[uuid.UUID | None, Query(description="id do grupo atual")] = None,
    assignee: Annotated[str | None, Query(description='"me", "none" ou o id do usuário')] = None,
    status: Annotated[list[StatusKind] | None, Query(description="kinds de status")] = None,
    q: Annotated[
        str | None,
        Query(max_length=200, description="busca: texto, comentários, número, cliente, contato"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
) -> TicketPage:
    rows, next_cursor = await service.list_tickets(
        db,
        auth,
        view=view,
        team=team,
        assignee=assignee,
        kinds=status or [],
        q=q,
        limit=limit,
        cursor=cursor,
    )
    paths = await service.category_paths(db)
    return TicketPage(
        items=[TicketListItem(**dict(_summary(t, paths)), has_news=news) for t, news in rows],
        next_cursor=next_cursor,
    )


@router.get("/counts", response_model=TicketCounts)
async def ticket_counts(auth: CurrentAuth, db: DB) -> TicketCounts:
    return TicketCounts(**await service.counts(db, auth))


@router.post("/next", response_model=TicketOut)
async def take_next(data: NextIn, auth: CurrentAuth, db: DB) -> TicketOut:
    ticket = await service.take_next(db, auth, data.team_id)
    return await _detail(db, auth, await service.load(db, auth, str(ticket.public_id)))


@router.post("", response_model=TicketOut, status_code=201)
async def create_ticket(
    data: TicketCreate, auth: CurrentAuth, db: DB, response: Response
) -> TicketOut:
    ticket = await service.create(db, auth, data)
    response.headers["Location"] = f"/api/v1/tickets/{ticket.public_id}"
    return await _detail(db, auth, await service.load(db, auth, str(ticket.public_id)))


@router.get("/{ticket_ref}", response_model=TicketOut)
async def get_ticket(ticket_ref: str, auth: CurrentAuth, db: DB, request: Request) -> TicketOut:
    ticket = await service.load(db, auth, ticket_ref)
    # Regra 6 do docs/08 §8.4: admin e auditor leem confidenciais, e isso fica na auditoria.
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
    await service.mark_read(db, auth, ticket)
    return await _detail(db, auth, ticket)


@router.patch("/{ticket_ref}", response_model=TicketOut)
async def update_ticket(
    ticket_ref: str, data: TicketUpdate, auth: CurrentAuth, db: DB
) -> TicketOut:
    await service.update(db, auth, await service.load(db, auth, ticket_ref), data)
    return await _detail(db, auth, await service.load(db, auth, ticket_ref))


@router.post("/{ticket_ref}/assign", response_model=TicketOut)
async def assign_ticket(ticket_ref: str, data: AssignIn, auth: CurrentAuth, db: DB) -> TicketOut:
    await service.assign(db, auth, await service.load(db, auth, ticket_ref), data.assignee)
    return await _detail(db, auth, await service.load(db, auth, ticket_ref))


@router.post("/{ticket_ref}/transfer", response_model=TicketOut)
async def transfer_ticket(
    ticket_ref: str, data: TransferIn, auth: CurrentAuth, db: DB
) -> TicketOut:
    ticket = await service.load(db, auth, ticket_ref)
    await service.transfer(db, auth, ticket, data.team_id, data.reason)
    # Quem transferiu pode ter perdido o acesso de alteração, mas continua vendo (regra 2).
    return await _detail(db, auth, await service.load(db, auth, ticket_ref))


@router.post("/{ticket_ref}/transitions", response_model=TicketOut)
async def transition_ticket(
    ticket_ref: str, data: TransitionIn, auth: CurrentAuth, db: DB
) -> TicketOut:
    await service.transition(db, auth, await service.load(db, auth, ticket_ref), data)
    return await _detail(db, auth, await service.load(db, auth, ticket_ref))


# 204: quem se retira de um chamado de outro grupo deixa de vê-lo.
@router.put("/{ticket_ref}/watchers/{user_id}", status_code=204)
async def add_watcher(ticket_ref: str, user_id: uuid.UUID, auth: CurrentAuth, db: DB) -> None:
    ticket = await service.load(db, auth, ticket_ref)
    await service.set_watcher(db, auth, ticket, user_id, watching=True)


@router.delete("/{ticket_ref}/watchers/{user_id}", status_code=204)
async def remove_watcher(ticket_ref: str, user_id: uuid.UUID, auth: CurrentAuth, db: DB) -> None:
    ticket = await service.load(db, auth, ticket_ref)
    await service.set_watcher(db, auth, ticket, user_id, watching=False)


@router.get("/{ticket_ref}/comments", response_model=CommentList)
async def list_comments(ticket_ref: str, auth: CurrentAuth, db: DB) -> CommentList:
    ticket = await service.load(db, auth, ticket_ref)
    rows = await db.scalars(
        select(TicketComment)
        .where(TicketComment.ticket_id == ticket.id)
        .order_by(TicketComment.created_at, TicketComment.id)
    )
    return CommentList(items=[_comment_out(c) for c in rows])


@router.post("/{ticket_ref}/comments", response_model=CommentOut, status_code=201)
async def add_comment(ticket_ref: str, data: CommentIn, auth: CurrentAuth, db: DB) -> CommentOut:
    ticket = await service.load(db, auth, ticket_ref)
    comment = await service.add_comment(db, auth, ticket, data)
    await db.refresh(comment)
    return _comment_out(comment)


@router.patch("/{ticket_ref}/comments/{comment_id}", response_model=CommentOut)
async def edit_comment(
    ticket_ref: str, comment_id: uuid.UUID, data: CommentIn, auth: CurrentAuth, db: DB
) -> CommentOut:
    ticket = await service.load(db, auth, ticket_ref)
    comment = await service.edit_comment(db, auth, ticket, comment_id, data)
    return _comment_out(comment)


@router.get("/{ticket_ref}/events", response_model=EventList)
async def list_events(ticket_ref: str, auth: CurrentAuth, db: DB) -> EventList:
    ticket = await service.load(db, auth, ticket_ref)
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
