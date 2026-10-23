"""API dos chamados (docs/05). O chamado é aceito pelo número ou pelo UUID."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request, Response

from chamados.core.i18n import request_locale, translate
from chamados.db.session import DB
from chamados.modules.identity.deps import CurrentAuth
from chamados.modules.tickets import queries, service
from chamados.modules.tickets.schemas import (
    AssigneesIn,
    AssignIn,
    BulkFailure,
    BulkResult,
    BulkStatusIn,
    CommentIn,
    CommentList,
    CommentOut,
    EventList,
    StatusKind,
    TicketCounts,
    TicketCreate,
    TicketOut,
    TicketPage,
    TicketUpdate,
    TicketView,
    TransferIn,
    TransitionIn,
)

router = APIRouter(prefix="/tickets", tags=["chamados"])


@router.get("", response_model=TicketPage)
async def list_tickets(
    auth: CurrentAuth,
    db: DB,
    view: Annotated[TicketView, Query(description="fila (aba da lista)")] = "all",
    team: Annotated[uuid.UUID | None, Query(description="id do grupo atual")] = None,
    assignee: Annotated[str | None, Query(description='"me" ou o id do usuário')] = None,
    status: Annotated[list[StatusKind] | None, Query(description="kinds de status")] = None,
    q: Annotated[
        str | None,
        Query(max_length=200, description="busca: texto, comentários, número, cliente, contato"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
) -> TicketPage:
    return await queries.list_page(
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


@router.get("/counts", response_model=TicketCounts)
async def ticket_counts(auth: CurrentAuth, db: DB) -> TicketCounts:
    return TicketCounts(**await service.counts(db, auth))


@router.post("/bulk/status", response_model=BulkResult)
async def bulk_status(
    data: BulkStatusIn, auth: CurrentAuth, db: DB, request: Request
) -> BulkResult:
    """Muda o status de vários chamados (supervisor do grupo ou admin)."""
    updated, failed = await service.bulk_status(db, auth, data.numbers, data.status_id)
    locale = request_locale(request)
    return BulkResult(
        updated=updated,
        failed=[BulkFailure(number=n, detail=translate(d, locale)) for n, d in failed],
    )


@router.post("", response_model=TicketOut, status_code=201)
async def create_ticket(
    data: TicketCreate, auth: CurrentAuth, db: DB, response: Response
) -> TicketOut:
    ticket = await service.create(db, auth, data)
    response.headers["Location"] = f"/api/v1/tickets/{ticket.public_id}"
    return await queries.load_detail(db, auth, str(ticket.public_id))


@router.get("/{ticket_ref}", response_model=TicketOut)
async def get_ticket(
    ticket_ref: str, auth: CurrentAuth, db: DB, request: Request, response: Response
) -> TicketOut:
    out = await queries.open_ticket(db, auth, await service.load(db, auth, ticket_ref), request)
    response.headers["ETag"] = out.etag
    return out


@router.patch("/{ticket_ref}", response_model=TicketOut)
async def update_ticket(
    ticket_ref: str,
    data: TicketUpdate,
    auth: CurrentAuth,
    db: DB,
    response: Response,
    if_match: Annotated[
        str | None,
        Header(description="o ETag do GET: com ele, 412 se os campos mudaram desde então"),
    ] = None,
) -> TicketOut:
    ticket = await service.load(db, auth, ticket_ref)
    await service.update(db, auth, ticket, data, if_match)
    out = await queries.load_detail(db, auth, ticket_ref)
    response.headers["ETag"] = out.etag
    return out


@router.post("/{ticket_ref}/assign", response_model=TicketOut)
async def assign_ticket(ticket_ref: str, data: AssignIn, auth: CurrentAuth, db: DB) -> TicketOut:
    await service.assign(db, auth, await service.load(db, auth, ticket_ref), data.assignee)
    return await queries.load_detail(db, auth, ticket_ref)


@router.put("/{ticket_ref}/assignees", response_model=TicketOut)
async def set_ticket_assignees(
    ticket_ref: str, data: AssigneesIn, auth: CurrentAuth, db: DB
) -> TicketOut:
    """Vários responsáveis de uma vez (ou o grupo inteiro): a lista completa."""
    ticket = await service.load(db, auth, ticket_ref)
    await service.set_assignees(db, auth, ticket, data.assignee_ids)
    return await queries.load_detail(db, auth, ticket_ref)


@router.post("/{ticket_ref}/transfer", response_model=TicketOut)
async def transfer_ticket(
    ticket_ref: str, data: TransferIn, auth: CurrentAuth, db: DB
) -> TicketOut:
    ticket = await service.load(db, auth, ticket_ref)
    await service.transfer(db, auth, ticket, data.team_id, data.assignee_id, data.reason)
    # Quem transferiu pode ter perdido o acesso de alteração, mas continua vendo (regra 2).
    return await queries.load_detail(db, auth, ticket_ref)


@router.post("/{ticket_ref}/transitions", response_model=TicketOut)
async def transition_ticket(
    ticket_ref: str, data: TransitionIn, auth: CurrentAuth, db: DB
) -> TicketOut:
    await service.transition(db, auth, await service.load(db, auth, ticket_ref), data)
    return await queries.load_detail(db, auth, ticket_ref)


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
    return await queries.comments(db, await service.load(db, auth, ticket_ref))


@router.post("/{ticket_ref}/comments", response_model=CommentOut, status_code=201)
async def add_comment(ticket_ref: str, data: CommentIn, auth: CurrentAuth, db: DB) -> CommentOut:
    ticket = await service.load(db, auth, ticket_ref)
    comment = await service.add_comment(db, auth, ticket, data)
    await db.refresh(comment)
    return queries.comment_out(comment)


@router.patch("/{ticket_ref}/comments/{comment_id}", response_model=CommentOut)
async def edit_comment(
    ticket_ref: str, comment_id: uuid.UUID, data: CommentIn, auth: CurrentAuth, db: DB
) -> CommentOut:
    ticket = await service.load(db, auth, ticket_ref)
    comment = await service.edit_comment(db, auth, ticket, comment_id, data)
    return queries.comment_out(comment)


@router.delete("/{ticket_ref}/comments/{comment_id}", status_code=204)
async def delete_comment(ticket_ref: str, comment_id: uuid.UUID, auth: CurrentAuth, db: DB) -> None:
    ticket = await service.load(db, auth, ticket_ref)
    await service.delete_comment(db, auth, ticket, comment_id)


@router.get("/{ticket_ref}/events", response_model=EventList)
async def list_events(ticket_ref: str, auth: CurrentAuth, db: DB) -> EventList:
    return await queries.events(db, await service.load(db, auth, ticket_ref))
