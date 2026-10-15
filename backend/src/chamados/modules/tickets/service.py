"""Operações nos chamados (docs/10). Toda ação passa por `rules.allowed_actions`, e toda leitura
pelo filtro de visibilidade. Cada mudança gera um evento no histórico (ticket_events).
"""

import base64
import json
import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy import ColumnElement, and_, exists, func, literal_column, or_, select, true
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager, defaultload, defer, raiseload, selectinload

from chamados.core.permissions import P, can
from chamados.core.text import optional_text, required_text
from chamados.modules.attachments import service as attachments
from chamados.modules.catalog.models import Category, ResolutionCode, TicketStatus
from chamados.modules.clients.models import Client
from chamados.modules.identity.deps import Auth
from chamados.modules.identity.models import User
from chamados.modules.organization.models import Department, Team, TeamMember
from chamados.modules.tickets import rules
from chamados.modules.tickets.models import (
    Ticket,
    TicketCoAssignee,
    TicketComment,
    TicketEvent,
    TicketRead,
    TicketTeam,
    TicketWatcher,
)
from chamados.modules.tickets.schemas import (
    CommentIn,
    TicketCreate,
    TicketUpdate,
    TicketView,
    TransitionIn,
)
from chamados.modules.tickets.visibility import assigned_to, ticket_visibility_filter

FORBIDDEN = "Você não tem permissão para esta ação."
Assignee = Literal["me"] | uuid.UUID


def ref(
    obj: User | Team | Category | Department | Client | TicketStatus | ResolutionCode | None,
) -> Any:
    """Referência gravada no histórico: id e nome na data do evento."""
    if obj is None:
        return None
    if isinstance(obj, User):
        return {"id": str(obj.public_id), "name": obj.display_name}
    if isinstance(obj, TicketStatus | ResolutionCode):
        return {"id": obj.id, "name": obj.name}
    if isinstance(obj, Client):
        return {"id": str(obj.public_id), "name": obj.label}
    return {"id": str(obj.public_id), "name": obj.name}


def add_event(
    db: AsyncSession, ticket: Ticket, event_type: str, auth: Auth, **payload: Any
) -> None:
    db.add(
        TicketEvent(
            ticket_id=ticket.id, event_type=event_type, actor_user_id=auth.user.id, payload=payload
        )
    )


# --- leitura ----------------------------------------------------------------------------------


def _by_ref(ticket_ref: str) -> ColumnElement[bool]:
    """O chamado é aceito pelo número (`1234`) ou pelo UUID (docs/05)."""
    if ticket_ref.isdigit() and len(ticket_ref) < 19:
        return Ticket.number == int(ticket_ref)
    try:
        return Ticket.public_id == uuid.UUID(ticket_ref)
    except ValueError:
        raise HTTPException(404, "Chamado não encontrado.") from None


async def load(db: AsyncSession, auth: Auth, ticket_ref: str) -> Ticket:
    """Chamado visível para o usuário: 404 se não existe, 403 se não pode vê-lo."""
    stmt = (
        select(Ticket, ticket_visibility_filter(auth.actor).label("visible"))
        .where(_by_ref(ticket_ref))
        .options(selectinload(Ticket.watchers), selectinload(Ticket.co_assignees))
        # Depois de uma alteração, relê tudo (a sessão não expira os objetos no commit).
        .execution_options(populate_existing=True)
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        raise HTTPException(404, "Chamado não encontrado.")
    ticket, visible = row
    if not visible:
        raise HTTPException(403, "Você não tem acesso a este chamado.")
    return ticket


def actions(auth: Auth, ticket: Ticket) -> set[str]:
    state = rules.TicketState(
        team_id=ticket.team_id,
        kind=ticket.status.kind,
        created_by_id=ticket.created_by_id,
        assignee_id=ticket.assignee_id,
        is_watcher=any(w.user_id == auth.user.id for w in ticket.watchers),
        co_assignee_ids=frozenset(c.user_id for c in ticket.co_assignees),
    )
    return rules.allowed_actions(auth.actor, state)


def require(auth: Auth, ticket: Ticket, action: str) -> None:
    if action not in actions(auth, ticket):
        raise HTTPException(403, FORBIDDEN)


async def category_paths(db: AsyncSession, tickets: Sequence[Ticket]) -> dict[int, str]:
    """Caminho de cada categoria na árvore (são poucas: carrega todas, se algum chamado tiver)."""
    if not any(t.category_id for t in tickets):
        return {}
    rows = {c.id: c for c in (await db.scalars(select(Category))).all()}

    def path(c: Category) -> str:
        return f"{path(rows[c.parent_id])} › {c.name}" if c.parent_id else c.name

    return {cid: path(c) for cid, c in rows.items()}


def _encode_cursor(t: Ticket) -> str:
    raw = json.dumps([t.created_at.isoformat(), t.id])
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        created_at, ticket_id = json.loads(base64.urlsafe_b64decode(cursor))
        return datetime.fromisoformat(created_at), int(ticket_id)
    except (ValueError, TypeError):
        raise HTTPException(422, "Cursor inválido.") from None


NEVER: ColumnElement[Any] = literal_column("'-infinity'::timestamptz")


def has_news(user_id: int) -> ColumnElement[bool]:
    """Comentário de outra pessoa depois da última visita (ou nunca aberto) (docs/13 §13.5)."""
    read_at = (
        select(TicketRead.read_at)
        .where(TicketRead.ticket_id == Ticket.id, TicketRead.user_id == user_id)
        # Dentro do EXISTS a correlação automática não alcança o chamado de fora.
        .correlate(Ticket)
        .scalar_subquery()
    )
    return exists().where(
        TicketComment.ticket_id == Ticket.id,
        TicketComment.author_id != user_id,
        TicketComment.deleted_at.is_(None),
        TicketComment.created_at > func.coalesce(read_at, NEVER),
    )


def time_spent() -> Any:
    """Soma do tempo gasto nas tarefas (não removidas) do chamado, em minutos."""
    return (
        select(func.coalesce(func.sum(TicketComment.time_spent_minutes), 0))
        .where(TicketComment.ticket_id == Ticket.id, TicketComment.deleted_at.is_(None))
        .correlate(Ticket)
        .scalar_subquery()
    )


ACTIVE = ("open", "waiting", "delivered")
# A aba Aguardando também mostra os entregues (à espera da revisão do supervisor).
WAITING = ("waiting", "delivered")
PT_BR: ColumnElement[Any] = literal_column("'pt_br'::regconfig")


def view_filter(auth: Auth, view: TicketView) -> ColumnElement[bool]:
    """As filas da lista (docs/10 §10.6). O status vem do join com ticket_statuses."""
    me = auth.user.id
    my_teams = Ticket.team_id.in_(auth.actor.teams)
    match view:
        case "mine":
            return and_(assigned_to(me), TicketStatus.kind.in_(ACTIVE))
        case "waiting":
            return and_(my_teams, TicketStatus.kind.in_(WAITING))
        case "watching":
            return and_(
                exists().where(TicketWatcher.ticket_id == Ticket.id, TicketWatcher.user_id == me),
                TicketStatus.kind.in_(ACTIVE),
            )
        case "all":
            return true()


def search_filter(q: str) -> ColumnElement[bool] | None:
    """Busca em português, sem acentos e por começo de palavra, no título, na descrição e nos
    comentários; também pelo número, pelo cliente e pelo contato."""
    words = re.findall(r"\w+", q)
    if not words:
        return None
    query = func.to_tsquery(PT_BR, " & ".join(f"{w}:*" for w in words))
    like = func.unaccent(f"%{q.strip()}%")
    rules: list[ColumnElement[bool]] = [
        Ticket.search_vector.op("@@")(query),
        exists().where(
            TicketComment.ticket_id == Ticket.id,
            TicketComment.deleted_at.is_(None),
            TicketComment.search_vector.op("@@")(query),
        ),
        func.unaccent(Ticket.beneficiary_name).ilike(like),
        exists().where(
            Client.id == Ticket.client_id,
            or_(
                func.unaccent(Client.name).ilike(like), func.unaccent(Client.trade_name).ilike(like)
            ),
        ),
    ]
    number = q.strip().removeprefix("#")
    if number.isdigit() and len(number) < 19:
        rules.append(Ticket.number == int(number))
    return or_(*rules)


def _ordered(stmt: Any) -> Any:
    """Ordenação padrão: o mais antigo primeiro (docs/10 §10.6)."""
    return stmt.order_by(Ticket.created_at, Ticket.id)


async def list_tickets(
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
) -> tuple[list[tuple[Ticket, bool, int]], str | None]:
    """Chamados visíveis de uma fila, com o aviso de novidade e o tempo gasto de cada um."""
    stmt = _ordered(
        select(Ticket, has_news(auth.user.id).label("has_news"), time_spent().label("minutes"))
        .join(Ticket.status)
        # A lista não mostra a descrição (até 50 mil caracteres por chamado), quem registrou nem
        # o código de resolução: sem eles, menos colunas e menos joins.
        .options(
            contains_eager(Ticket.status),
            defer(Ticket.description),
            raiseload(Ticket.created_by),
            raiseload(Ticket.resolution_code),
            defaultload(Ticket.category).raiseload(Category.default_team),
            defaultload(Ticket.assignee).raiseload(User.role),
        )
        .where(ticket_visibility_filter(auth.actor), view_filter(auth, view))
        .limit(limit + 1)
    )
    if q and (search := search_filter(q)) is not None:
        stmt = stmt.where(search)
    if team is not None:
        stmt = stmt.where(Ticket.team.has(Team.public_id == team))
    if assignee == "me":
        stmt = stmt.where(assigned_to(auth.user.id))
    elif assignee is not None:
        try:
            assignee_id = uuid.UUID(assignee)
        except ValueError:
            raise HTTPException(422, 'Responsável: use "me" ou o id.') from None
        stmt = stmt.where(
            or_(
                Ticket.assignee.has(User.public_id == assignee_id),
                Ticket.co_assignees.any(TicketCoAssignee.user.has(User.public_id == assignee_id)),
            )
        )
    if kinds:
        stmt = stmt.where(TicketStatus.kind.in_(kinds))
    if cursor:
        created_at, ticket_id = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Ticket.created_at > created_at,
                and_(Ticket.created_at == created_at, Ticket.id > ticket_id),
            )
        )
    rows = [(t, news, minutes) for t, news, minutes in (await db.execute(stmt)).all()]
    next_cursor = _encode_cursor(rows[limit - 1][0]) if len(rows) > limit else None
    return rows[:limit], next_cursor


async def counts(db: AsyncSession, auth: Auth) -> dict[str, int]:
    """Quantos chamados visíveis há em cada fila, numa consulta só."""
    views: tuple[TicketView, ...] = ("mine", "waiting", "watching")
    row = (
        await db.execute(
            select(*(func.count().filter(view_filter(auth, v)).label(v) for v in views))
            .select_from(Ticket)
            .join(Ticket.status)
            .where(ticket_visibility_filter(auth.actor))
        )
    ).one()
    return dict(row._mapping)


async def mark_read(db: AsyncSession, auth: Auth, ticket: Ticket) -> None:
    """Guarda a visita: os comentários até agora deixam de ser novidade."""
    await db.execute(
        insert(TicketRead)
        .values(ticket_id=ticket.id, user_id=auth.user.id)
        .on_conflict_do_update(
            index_elements=[TicketRead.ticket_id, TicketRead.user_id],
            set_={"read_at": func.now()},
        )
    )
    await db.commit()


# --- apoio --------------------------------------------------------------------------------------


async def _default_status(db: AsyncSession, kind: str) -> TicketStatus:
    status = await db.scalar(
        select(TicketStatus).where(TicketStatus.kind == kind, TicketStatus.is_default_for_kind)
    )
    if status is None:
        raise HTTPException(500, f"Status padrão do tipo {kind} não configurado.")
    return status


async def _status(db: AsyncSession, status_id: int) -> TicketStatus:
    status = await db.get(TicketStatus, status_id)
    if status is None:
        raise HTTPException(422, "Status não encontrado.")
    return status


def _apply_status(ticket: Ticket, before: TicketStatus | None, status: TicketStatus) -> None:
    """Status escolhido livremente: acerta a data de conclusão e a contagem de reaberturas."""
    was_closed = before is not None and before.kind == "closed"
    ticket.status = status
    if status.kind == "closed" and not was_closed:
        ticket.closed_at = func.now()
    elif status.kind != "closed" and was_closed:
        ticket.closed_at = None
        ticket.resolution_code_id = None
        if status.kind in ACTIVE:
            ticket.reopened_count += 1


INACTIVE = {
    Category: "Categoria não encontrada ou inativa.",
    Team: "Grupo não encontrado ou inativo.",
    Department: "Setor não encontrado ou inativo.",
    Client: "Cliente não encontrado ou inativo.",
}


async def _active[M: (Category, Team, Department, Client)](
    db: AsyncSession, model: type[M], public_id: uuid.UUID
) -> M:
    """Cadastro ativo pelo id público; 422 se não existe ou foi inativado."""
    found = await db.scalar(select(model).where(model.public_id == public_id, model.is_active))
    if found is None:
        raise HTTPException(422, INACTIVE[model])
    return found


async def _team_member(db: AsyncSession, public_id: uuid.UUID, team_id: int) -> User:
    return (await _team_members(db, {public_id}, team_id))[0]


async def _team_members(db: AsyncSession, public_ids: set[uuid.UUID], team_id: int) -> list[User]:
    users = (
        await db.scalars(
            select(User)
            .join(TeamMember, TeamMember.user_id == User.id)
            .where(User.public_id.in_(public_ids), User.is_active, TeamMember.team_id == team_id)
        )
    ).all()
    if len(users) != len(public_ids):
        raise HTTPException(422, "O responsável precisa ser um membro ativo do grupo.")
    return list(users)


async def _add_watchers(
    db: AsyncSession,
    auth: Auth,
    ticket: Ticket,
    user_ids: list[uuid.UUID],
    kind: Literal["watcher", "mentioned"],
) -> None:
    """Inclui observadores (ou mencionados). Quem já acompanha continua como está."""
    if not user_ids:
        return
    users = (
        await db.scalars(select(User).where(User.public_id.in_(user_ids), User.is_active))
    ).all()
    if len(users) != len(set(user_ids)):
        raise HTTPException(422, "Observador ou mencionado não encontrado ou inativo.")
    current = set(
        (
            await db.scalars(
                select(TicketWatcher.user_id).where(TicketWatcher.ticket_id == ticket.id)
            )
        ).all()
    )
    for user in users:
        if user.id in current:
            continue
        db.add(
            TicketWatcher(ticket_id=ticket.id, user_id=user.id, kind=kind, added_by=auth.user.id)
        )
        add_event(db, ticket, "watcher.added", auth, user=ref(user), kind=kind)


async def _comment(
    db: AsyncSession,
    auth: Auth,
    ticket: Ticket,
    body: str,
    mention_ids: list[uuid.UUID] | None = None,
    attachment_ids: list[uuid.UUID] | None = None,
    *,
    time_spent_minutes: int | None = None,
    done_at: datetime | None = None,
    is_solution: bool = False,
) -> TicketComment:
    comment = TicketComment(
        ticket_id=ticket.id,
        author_id=auth.user.id,
        body=body,
        time_spent_minutes=time_spent_minutes,
        is_solution=is_solution,
    )
    if done_at is not None:
        comment.done_at = _done_at(done_at)
    db.add(comment)
    await db.flush()
    await _add_watchers(db, auth, ticket, mention_ids or [], "mentioned")
    await attachments.link(db, auth, ticket, attachment_ids or [], comment)
    ticket.updated_at = func.now()
    return comment


async def time_by_person(db: AsyncSession, ticket: Ticket) -> list[tuple[User, int]]:
    """Tempo gasto nos comentários somado por autor, de quem gastou mais para quem gastou menos."""
    total = func.sum(TicketComment.time_spent_minutes)
    rows = await db.execute(
        select(User, total)
        .join(TicketComment, TicketComment.author_id == User.id)
        .where(
            TicketComment.ticket_id == ticket.id,
            TicketComment.time_spent_minutes.is_not(None),
            TicketComment.deleted_at.is_(None),
        )
        .group_by(User.id)
        .order_by(total.desc(), User.display_name)
    )
    return [(user, minutes or 0) for user, minutes in rows]


# Folga para o relógio do computador de quem registra estar um pouco adiantado.
CLOCK_SKEW = timedelta(minutes=5)


def _not_future(value: datetime, message: str) -> datetime:
    if value > datetime.now(UTC) + CLOCK_SKEW:
        raise HTTPException(422, message)
    return value.astimezone(UTC)


def _started_at(value: datetime) -> datetime:
    return _not_future(value, "O início não pode ficar no futuro.")


def _done_at(value: datetime) -> datetime:
    return _not_future(value, "A data da tarefa não pode ficar no futuro.")


# --- registro ---------------------------------------------------------------------------------


async def create(db: AsyncSession, auth: Auth, data: TicketCreate) -> Ticket:
    """Registro (docs/10 §10.4). O grupo vem da categoria quando não é informado (roteamento)."""
    if not can(auth.actor, P.TICKET_CREATE):
        raise HTTPException(403, FORBIDDEN)
    category = await _active(db, Category, data.category_id) if data.category_id else None
    if data.team_id is not None:
        team = await _active(db, Team, data.team_id)
    elif category and category.default_team is not None and category.default_team.is_active:
        team = category.default_team
    elif category:
        raise HTTPException(422, "Escolha o grupo: a categoria não tem um grupo padrão ativo.")
    else:
        raise HTTPException(422, "Escolha o grupo do chamado.")
    if team.id not in auth.actor.teams:
        raise HTTPException(403, "Você só registra chamados nos grupos de que é membro.")
    department = await _active(db, Department, data.department_id) if data.department_id else None
    client = await _active(db, Client, data.client_id)
    if data.watcher_ids and not can(auth.actor, P.TICKET_WATCH):
        raise HTTPException(403, FORBIDDEN)
    if data.status_id is not None and not can(auth.actor, P.TICKET_TRANSITION):
        raise HTTPException(403, FORBIDDEN)
    status = await (
        _status(db, data.status_id) if data.status_id is not None else _default_status(db, "open")
    )

    if data.assignee == "me" or data.assignee == auth.user.public_id:
        assignee = auth.user
    else:
        if not can(auth.actor, P.TICKET_ASSIGN_OTHERS, team.id):
            raise HTTPException(403, FORBIDDEN)
        assignee = await _team_member(db, data.assignee, team.id)
    co_assignees: list[User] = []
    if data.co_assignee_ids:
        if not can(auth.actor, P.TICKET_ASSIGN_OTHERS, team.id):
            raise HTTPException(403, FORBIDDEN)
        co_assignees = await _team_members(
            db, set(data.co_assignee_ids) - {assignee.public_id}, team.id
        )

    ticket = Ticket(
        title=data.title,
        description=data.description,
        type=data.type or (category.default_type if category else "incident"),
        created_by_id=auth.user.id,
        department_id=department.id if department else None,
        client_id=client.id,
        beneficiary_name=optional_text(data.beneficiary_name),
        team_id=team.id,
        assignee_id=assignee.id,
        category_id=category.id if category else None,
        status_id=status.id,
        first_assigned_at=func.now(),
    )
    _apply_status(ticket, None, status)
    if data.started_at is not None:
        ticket.started_at = _started_at(data.started_at)
    db.add(ticket)
    await db.flush()
    db.add(TicketTeam(ticket_id=ticket.id, team_id=team.id))
    await attachments.link(db, auth, ticket, data.attachment_ids)
    db.add_all(TicketCoAssignee(ticket_id=ticket.id, user_id=u.id) for u in co_assignees)
    created: dict[str, Any] = {"team": ref(team), "assignee": ref(assignee)}
    if co_assignees:
        created["co_assignees"] = [ref(u) for u in co_assignees]
    add_event(db, ticket, "ticket.created", auth, **created)
    await _add_watchers(db, auth, ticket, data.watcher_ids, "watcher")
    await _add_watchers(db, auth, ticket, data.mention_ids, "mentioned")
    await db.commit()
    return ticket


# --- alterações -------------------------------------------------------------------------------

EDIT_FIELDS = {
    "title",
    "description",
    "category_id",
    "type",
    "department_id",
    "client_id",
    "beneficiary_name",
    "started_at",
}


def _change_status(db: AsyncSession, auth: Auth, ticket: Ticket, status: TicketStatus) -> None:
    """Status escolhido livremente (set_status); um concluído pede set_status_closed."""
    require(auth, ticket, "set_status")
    if status.kind == "closed":
        require(auth, ticket, "set_status_closed")
    if status.id != ticket.status_id:
        before = ticket.status
        add_event(
            db, ticket, "ticket.status_changed", auth, **{"from": ref(before), "to": ref(status)}
        )
        _apply_status(ticket, before, status)


async def bulk_status(
    db: AsyncSession, auth: Auth, numbers: list[int], status_id: int
) -> tuple[list[int], list[tuple[int, str]]]:
    """Mesmo status em vários chamados (ação bulk). Cada chamado passa pelas próprias regras; os
    que não podem mudar ficam de fora, com o motivo, e os demais mudam juntos."""
    status = await _status(db, status_id)
    updated: list[int] = []
    failed: list[tuple[int, str]] = []
    for number in dict.fromkeys(numbers):
        try:
            ticket = await load(db, auth, str(number))
            require(auth, ticket, "bulk")
            _change_status(db, auth, ticket, status)
        except HTTPException as e:
            failed.append((number, str(e.detail)))
        else:
            updated.append(number)
    await db.commit()
    return updated, failed


async def update(db: AsyncSession, auth: Auth, ticket: Ticket, data: TicketUpdate) -> None:
    """Campos do chamado (docs/08 §8.5)."""
    changes = data.model_dump(exclude_unset=True)
    attachment_ids = changes.pop("attachment_ids", None) or []
    if changes.keys() & EDIT_FIELDS or attachment_ids:
        require(auth, ticket, "edit")
    # Imagens coladas ao editar a descrição.
    await attachments.link(db, auth, ticket, attachment_ids)
    if changes.get("status_id") is not None:
        _change_status(db, auth, ticket, await _status(db, changes["status_id"]))
    diff: dict[str, dict[str, Any]] = {}

    def put(field: str, new: Any, before: Any = None, after: Any = None) -> None:
        old = getattr(ticket, field)
        if old != new:
            key = field.removesuffix("_id")
            diff[key] = {
                "from": old if before is None else before,
                "to": new if after is None else after,
            }
            setattr(ticket, field, new)

    if changes.get("title") is not None:
        put("title", changes["title"])
    if changes.get("description") is not None:
        put("description", changes["description"])
    if changes.get("type") is not None:
        put("type", changes["type"])
    if "category_id" in changes:
        new_id = changes["category_id"]
        category = await _active(db, Category, new_id) if new_id else None
        put("category_id", category.id if category else None, ref(ticket.category), ref(category))
    if "department_id" in changes:
        new_id = changes["department_id"]
        dept = await _active(db, Department, new_id) if new_id else None
        put("department_id", dept.id if dept else None, ref(ticket.department), ref(dept))
    if "client_id" in changes:
        if changes["client_id"] is None:
            raise HTTPException(422, "O chamado precisa de um cliente.")
        client = await _active(db, Client, changes["client_id"])
        put("client_id", client.id, ref(ticket.client), ref(client))
    if "beneficiary_name" in changes:
        put("beneficiary_name", optional_text(changes["beneficiary_name"]))
    if changes.get("started_at") is not None:
        new = _started_at(changes["started_at"])
        put("started_at", new, ticket.started_at.isoformat(), new.isoformat())

    if diff:
        add_event(db, ticket, "ticket.updated", auth, changes=diff)
    await db.commit()


async def add_comment(
    db: AsyncSession, auth: Auth, ticket: Ticket, data: CommentIn
) -> TicketComment:
    require(auth, ticket, "comment")
    comment = await _comment(
        db,
        auth,
        ticket,
        required_text(data.body, "Escreva o comentário."),
        data.mention_ids,
        data.attachment_ids,
        time_spent_minutes=data.time_spent_minutes,
        done_at=data.done_at,
    )
    await db.commit()
    return comment


async def _own_comment(
    db: AsyncSession, auth: Auth, ticket: Ticket, comment_id: uuid.UUID
) -> TicketComment:
    """Tarefa (não removida) do chamado que o autor pode alterar."""
    comment = await db.scalar(
        select(TicketComment).where(
            TicketComment.public_id == comment_id,
            TicketComment.ticket_id == ticket.id,
            TicketComment.deleted_at.is_(None),
        )
    )
    if comment is None:
        raise HTTPException(404, "Comentário não encontrado.")
    require(auth, ticket, "comment")
    if comment.author_id != auth.user.id:
        raise HTTPException(403, "Só o autor altera a tarefa.")
    return comment


async def edit_comment(
    db: AsyncSession,
    auth: Auth,
    ticket: Ticket,
    comment_id: uuid.UUID,
    data: CommentIn,
) -> TicketComment:
    """Só o autor, a qualquer momento; a versão anterior fica no histórico (docs/10 §10.6)."""
    comment = await _own_comment(db, auth, ticket, comment_id)
    body = required_text(data.body, "Escreva o comentário.")
    minutes = data.time_spent_minutes
    done_at = _done_at(data.done_at) if data.done_at is not None else comment.done_at
    changed_time = minutes != comment.time_spent_minutes
    changed_date = done_at != comment.done_at
    if body != comment.body or changed_time or changed_date:
        before: dict[str, Any] = {"before": comment.body}
        if changed_time:
            before["before_time_spent_minutes"] = comment.time_spent_minutes
        if changed_date:
            before["before_done_at"] = comment.done_at.isoformat()
        add_event(db, ticket, "comment.edited", auth, comment_id=str(comment.public_id), **before)
        comment.body = body
        comment.time_spent_minutes = minutes
        comment.done_at = done_at
        comment.edited_at = func.now()
    await _add_watchers(db, auth, ticket, data.mention_ids, "mentioned")
    await attachments.link(db, auth, ticket, data.attachment_ids, comment)
    await db.commit()
    await db.refresh(comment)
    return comment


async def delete_comment(
    db: AsyncSession, auth: Auth, ticket: Ticket, comment_id: uuid.UUID
) -> None:
    """Só o autor. A tarefa sai da tela e do tempo gasto; o texto fica no histórico."""
    comment = await _own_comment(db, auth, ticket, comment_id)
    add_event(
        db,
        ticket,
        "comment.deleted",
        auth,
        comment_id=str(comment.public_id),
        body=comment.body,
        time_spent_minutes=comment.time_spent_minutes,
    )
    comment.deleted_at = func.now()
    ticket.updated_at = func.now()
    await db.commit()


async def assign(db: AsyncSession, auth: Auth, ticket: Ticket, assignee: Assignee) -> None:
    """Assumir ou atribuir a outro membro (supervisor) (docs/08 §8.5)."""
    if assignee == "me" or assignee == auth.user.public_id:
        require(auth, ticket, "assign_self")
        new = auth.user
    else:
        require(auth, ticket, "assign_others")
        new = await _team_member(db, assignee, ticket.team_id)
    if new.id == ticket.assignee_id:
        return
    ticket.co_assignees[:] = [c for c in ticket.co_assignees if c.user_id != new.id]
    add_event(db, ticket, "ticket.assigned", auth, **{"from": ref(ticket.assignee), "to": ref(new)})
    ticket.assignee_id = new.id
    await db.commit()


async def transfer(
    db: AsyncSession,
    auth: Auth,
    ticket: Ticket,
    team_id: uuid.UUID,
    assignee_id: uuid.UUID,
    reason: str,
) -> None:
    """Vai para o outro grupo, com um responsável de lá; o anterior continua vendo (docs/10)."""
    require(auth, ticket, "transfer")
    team = await _active(db, Team, team_id)
    if team.id == ticket.team_id:
        raise HTTPException(422, "O chamado já está neste grupo.")
    assignee = await _team_member(db, assignee_id, team.id)
    comment = await _comment(
        db, auth, ticket, required_text(reason, "Informe o motivo da transferência.")
    )
    payload: dict[str, Any] = {
        "from": ref(ticket.team),
        "to": ref(team),
        "comment_id": str(comment.public_id),
    }
    payload["assignee"] = {"from": ref(ticket.assignee), "to": ref(assignee)}
    if ticket.co_assignees:
        payload["co_unassigned"] = [ref(c.user) for c in ticket.co_assignees]
    if ticket.status.kind != "open":
        status = await _default_status(db, "open")
        payload["status"] = {"from": ref(ticket.status), "to": ref(status)}
        ticket.status_id = status.id
    add_event(db, ticket, "ticket.transferred", auth, **payload)
    ticket.team_id = team.id
    ticket.assignee_id = assignee.id
    ticket.co_assignees.clear()
    known = await db.get(TicketTeam, (ticket.id, team.id))
    if known is None:
        db.add(TicketTeam(ticket_id=ticket.id, team_id=team.id))
    await db.commit()


async def transition(db: AsyncSession, auth: Auth, ticket: Ticket, data: TransitionIn) -> None:
    """Mudança de status pelo fluxo (docs/10 §10.5), com o comentário na mesma ação."""
    require(auth, ticket, data.action)
    tr = rules.TRANSITIONS[data.action]
    text = (data.comment or "").strip()
    if tr.comment_required and not text:
        raise HTTPException(422, "Escreva o comentário: ele é obrigatório nesta mudança.")
    if data.time_spent_minutes and not text:
        raise HTTPException(422, "Escreva o comentário do tempo gasto.")
    code = None
    if tr.resolution_required:
        code = await db.scalar(
            select(ResolutionCode).where(
                ResolutionCode.id == data.resolution_code_id, ResolutionCode.is_active
            )
        )
        if code is None:
            raise HTTPException(422, "Escolha o código de resolução.")
    status = await _default_status(db, tr.to_kind)
    payload: dict[str, Any] = {
        "action": data.action,
        "from": ref(ticket.status),
        "to": ref(status),
    }
    if text:
        comment = await _comment(
            db,
            auth,
            ticket,
            text,
            attachment_ids=data.attachment_ids,
            time_spent_minutes=data.time_spent_minutes,
            is_solution=data.action == "close",
        )
        payload["comment_id"] = str(comment.public_id)
    if code is not None:
        payload["resolution_code"] = ref(code)
    add_event(db, ticket, "ticket.status_changed", auth, **payload)

    ticket.status_id = status.id
    if data.action == "close":
        ticket.resolution_code_id = code.id if code else None
        ticket.closed_at = func.now()
    elif data.action == "reopen":
        # Volta para o mesmo responsável (docs/10 §10.5).
        ticket.reopened_count += 1
        ticket.resolution_code_id = None
        ticket.closed_at = None
    await db.commit()


async def set_watcher(
    db: AsyncSession, auth: Auth, ticket: Ticket, user_id: uuid.UUID, *, watching: bool
) -> None:
    """Qualquer um se inclui ou se retira; incluir ou retirar colegas exige ser do grupo."""
    require(auth, ticket, "watch_self" if user_id == auth.user.public_id else "manage_watchers")
    if watching:
        await _add_watchers(db, auth, ticket, [user_id], "watcher")
    else:
        watcher = next((w for w in ticket.watchers if w.user.public_id == user_id), None)
        if watcher is None:
            raise HTTPException(404, "Este usuário não acompanha o chamado.")
        add_event(db, ticket, "watcher.removed", auth, user=ref(watcher.user))
        await db.delete(watcher)
    await db.commit()
