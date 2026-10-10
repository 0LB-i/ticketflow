"""Operações nos chamados (docs/10). Toda ação passa por `rules.allowed_actions`, e toda leitura
pelo filtro de visibilidade. Cada mudança gera um evento no histórico (ticket_events).
"""

import base64
import json
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from chamados.core.permissions import P, can
from chamados.modules.catalog.models import Category, ResolutionCode, TicketStatus
from chamados.modules.identity.deps import Auth
from chamados.modules.identity.models import User
from chamados.modules.organization.models import Department, Team, TeamMember
from chamados.modules.tickets import rules
from chamados.modules.tickets.models import (
    Ticket,
    TicketComment,
    TicketEvent,
    TicketTeam,
    TicketWatcher,
)
from chamados.modules.tickets.schemas import TicketCreate, TicketUpdate, TransitionIn
from chamados.modules.tickets.visibility import ticket_visibility_filter

COMMENT_EDIT_WINDOW = timedelta(minutes=10)
FORBIDDEN = "Você não tem permissão para esta ação."
Assignee = Literal["me"] | uuid.UUID | None


def ref(obj: User | Team | Category | Department | TicketStatus | ResolutionCode | None) -> Any:
    """Referência gravada no histórico: id e nome na data do evento."""
    if obj is None:
        return None
    if isinstance(obj, User):
        return {"id": str(obj.public_id), "name": obj.full_name}
    if isinstance(obj, TicketStatus | ResolutionCode):
        return {"id": obj.id, "name": obj.name}
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
        .options(selectinload(Ticket.watchers))
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
    )
    return rules.allowed_actions(auth.actor, state)


def require(auth: Auth, ticket: Ticket, action: str) -> None:
    if action not in actions(auth, ticket):
        raise HTTPException(403, FORBIDDEN)


async def category_paths(db: AsyncSession) -> dict[int, str]:
    """Caminho de cada categoria na árvore (são poucas: carrega todas)."""
    rows = {c.id: c for c in (await db.scalars(select(Category))).all()}

    def path(c: Category) -> str:
        return f"{path(rows[c.parent_id])} › {c.name}" if c.parent_id else c.name

    return {cid: path(c) for cid, c in rows.items()}


def _encode_cursor(t: Ticket) -> str:
    raw = json.dumps([t.priority, t.created_at.isoformat(), t.id])
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[int, datetime, int]:
    try:
        priority, created_at, ticket_id = json.loads(base64.urlsafe_b64decode(cursor))
        return int(priority), datetime.fromisoformat(created_at), int(ticket_id)
    except (ValueError, TypeError):
        raise HTTPException(422, "Cursor inválido.") from None


async def list_tickets(
    db: AsyncSession,
    auth: Auth,
    *,
    team: uuid.UUID | None,
    assignee: str | None,
    kinds: Sequence[str],
    limit: int,
    cursor: str | None,
) -> tuple[list[Ticket], str | None]:
    """Chamados visíveis na ordenação padrão: prioridade, depois o mais antigo (docs/10 §10.6)."""
    stmt = (
        select(Ticket)
        .join(Ticket.status)
        .where(ticket_visibility_filter(auth.actor))
        .order_by(Ticket.priority.desc(), Ticket.created_at, Ticket.id)
        .limit(limit + 1)
    )
    if team is not None:
        stmt = stmt.where(Ticket.team.has(Team.public_id == team))
    if assignee == "me":
        stmt = stmt.where(Ticket.assignee_id == auth.user.id)
    elif assignee == "none":
        stmt = stmt.where(Ticket.assignee_id.is_(None))
    elif assignee is not None:
        try:
            assignee_id = uuid.UUID(assignee)
        except ValueError:
            raise HTTPException(422, 'Responsável: use "me", "none" ou o id.') from None
        stmt = stmt.where(Ticket.assignee.has(User.public_id == assignee_id))
    if kinds:
        stmt = stmt.where(TicketStatus.kind.in_(kinds))
    if cursor:
        priority, created_at, ticket_id = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Ticket.priority < priority,
                and_(
                    Ticket.priority == priority,
                    or_(
                        Ticket.created_at > created_at,
                        and_(Ticket.created_at == created_at, Ticket.id > ticket_id),
                    ),
                ),
            )
        )
    rows = list((await db.scalars(stmt)).all())
    next_cursor = _encode_cursor(rows[limit - 1]) if len(rows) > limit else None
    return rows[:limit], next_cursor


# --- apoio --------------------------------------------------------------------------------------


async def _default_status(db: AsyncSession, kind: str) -> TicketStatus:
    status = await db.scalar(
        select(TicketStatus).where(TicketStatus.kind == kind, TicketStatus.is_default_for_kind)
    )
    if status is None:
        raise HTTPException(500, f"Status padrão do tipo {kind} não configurado.")
    return status


async def _active_category(db: AsyncSession, public_id: uuid.UUID) -> Category:
    category = await db.scalar(
        select(Category).where(Category.public_id == public_id, Category.is_active)
    )
    if category is None:
        raise HTTPException(422, "Categoria não encontrada ou inativa.")
    return category


async def _active_team(db: AsyncSession, public_id: uuid.UUID) -> Team:
    team = await db.scalar(select(Team).where(Team.public_id == public_id, Team.is_active))
    if team is None:
        raise HTTPException(422, "Grupo não encontrado ou inativo.")
    return team


async def _active_department(db: AsyncSession, public_id: uuid.UUID | None) -> Department | None:
    if public_id is None:
        return None
    dept = await db.scalar(
        select(Department).where(Department.public_id == public_id, Department.is_active)
    )
    if dept is None:
        raise HTTPException(422, "Setor não encontrado ou inativo.")
    return dept


async def _team_member(db: AsyncSession, public_id: uuid.UUID, team_id: int) -> User:
    user = await db.scalar(
        select(User)
        .join(TeamMember, TeamMember.user_id == User.id)
        .where(User.public_id == public_id, User.is_active, TeamMember.team_id == team_id)
    )
    if user is None:
        raise HTTPException(422, "O responsável precisa ser um membro ativo do grupo.")
    return user


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
    *,
    is_solution: bool = False,
) -> TicketComment:
    comment = TicketComment(
        ticket_id=ticket.id, author_id=auth.user.id, body=body, is_solution=is_solution
    )
    db.add(comment)
    await db.flush()
    await _add_watchers(db, auth, ticket, mention_ids or [], "mentioned")
    ticket.updated_at = func.now()
    return comment


def _text(value: str | None, message: str) -> str:
    text = (value or "").strip()
    if not text:
        raise HTTPException(422, message)
    return text


# --- registro ---------------------------------------------------------------------------------


async def create(db: AsyncSession, auth: Auth, data: TicketCreate) -> Ticket:
    """Registro (docs/10 §10.4). O grupo vem da categoria quando não é informado (roteamento)."""
    if not can(auth.actor, P.TICKET_CREATE):
        raise HTTPException(403, FORBIDDEN)
    category = await _active_category(db, data.category_id)
    if data.team_id is not None:
        team = await _active_team(db, data.team_id)
    elif category.default_team is not None and category.default_team.is_active:
        team = category.default_team
    else:
        raise HTTPException(422, "Escolha o grupo: a categoria não tem um grupo padrão ativo.")
    if team.id not in auth.actor.teams:
        raise HTTPException(403, "Você só registra chamados nos grupos de que é membro.")
    department = await _active_department(db, data.department_id)
    if data.watcher_ids and not can(auth.actor, P.TICKET_WATCH):
        raise HTTPException(403, FORBIDDEN)

    assignee: User | None = None
    if data.assignee == "me" or data.assignee == auth.user.public_id:
        assignee = auth.user
    elif data.assignee is not None:
        if not can(auth.actor, P.TICKET_ASSIGN_OTHERS, team.id):
            raise HTTPException(403, "Só o supervisor do grupo registra para outro membro.")
        assignee = await _team_member(db, data.assignee, team.id)

    ticket = Ticket(
        title=data.title,
        description=data.description,
        type=data.type or category.default_type,
        created_by_id=auth.user.id,
        department_id=department.id if department else None,
        beneficiary_name=(data.beneficiary_name or "").strip() or None,
        team_id=team.id,
        assignee_id=assignee.id if assignee else None,
        category_id=category.id,
        status_id=(await _default_status(db, "open")).id,
        impact=data.impact,
        urgency=data.urgency,
        priority=rules.priority_for(data.impact, data.urgency),
        first_assigned_at=func.now() if assignee else None,
    )
    db.add(ticket)
    await db.flush()
    db.add(TicketTeam(ticket_id=ticket.id, team_id=team.id))
    add_event(db, ticket, "ticket.created", auth, team=ref(team), assignee=ref(assignee))
    await _add_watchers(db, auth, ticket, data.watcher_ids, "watcher")
    await _add_watchers(db, auth, ticket, data.mention_ids, "mentioned")
    await db.commit()
    return ticket


# --- alterações -------------------------------------------------------------------------------

EDIT_FIELDS = {"title", "description", "category_id", "type", "department_id", "beneficiary_name"}
PRIORITY_FIELDS = {"impact", "urgency", "priority", "priority_reason"}


async def update(db: AsyncSession, auth: Auth, ticket: Ticket, data: TicketUpdate) -> None:
    """Campos do chamado (docs/08 §8.5). Forçar outra prioridade exige motivo (docs/10 §10.3)."""
    changes = data.model_dump(exclude_unset=True)
    if changes.keys() & EDIT_FIELDS:
        require(auth, ticket, "edit")
    if changes.keys() & PRIORITY_FIELDS:
        require(auth, ticket, "set_priority")
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
    if changes.get("category_id") is not None:
        category = await _active_category(db, changes["category_id"])
        put("category_id", category.id, ref(ticket.category), ref(category))
    if "department_id" in changes:
        dept = await _active_department(db, changes["department_id"])
        put("department_id", dept.id if dept else None, ref(ticket.department), ref(dept))
    if "beneficiary_name" in changes:
        put("beneficiary_name", (changes["beneficiary_name"] or "").strip() or None)

    reason = None
    if changes.get("impact") is not None:
        put("impact", changes["impact"])
    if changes.get("urgency") is not None:
        put("urgency", changes["urgency"])
    computed = rules.priority_for(ticket.impact, ticket.urgency)
    forced = changes.get("priority")
    if forced is not None and forced != computed:
        reason = _text(changes.get("priority_reason"), "Informe o motivo para forçar a prioridade.")
        put("priority", forced)
        put("priority_overridden", True)
    elif "priority" in changes or diff.keys() & {"impact", "urgency"}:
        # Mudar impacto ou urgência recalcula; priority nula (ou o valor da matriz) desfaz o
        # "forçado".
        put("priority", computed)
        put("priority_overridden", False)

    if diff:
        payload: dict[str, Any] = {"changes": diff}
        if reason:
            payload["reason"] = reason
        add_event(db, ticket, "ticket.updated", auth, **payload)
    await db.commit()


async def add_comment(
    db: AsyncSession, auth: Auth, ticket: Ticket, body: str, mention_ids: list[uuid.UUID]
) -> TicketComment:
    require(auth, ticket, "comment")
    comment = await _comment(db, auth, ticket, _text(body, "Escreva o comentário."), mention_ids)
    await db.commit()
    return comment


async def edit_comment(
    db: AsyncSession,
    auth: Auth,
    ticket: Ticket,
    comment_id: uuid.UUID,
    body: str,
    mention_ids: list[uuid.UUID],
) -> TicketComment:
    """Só o autor, por 10 minutos; a versão anterior fica no histórico (docs/10 §10.6)."""
    comment = await db.scalar(
        select(TicketComment).where(
            TicketComment.public_id == comment_id, TicketComment.ticket_id == ticket.id
        )
    )
    if comment is None:
        raise HTTPException(404, "Comentário não encontrado.")
    require(auth, ticket, "comment")
    if comment.author_id != auth.user.id:
        raise HTTPException(403, "Só o autor edita o comentário.")
    if await db.scalar(select(func.now() > comment.created_at + COMMENT_EDIT_WINDOW)):
        raise HTTPException(409, "O prazo de 10 minutos para editar este comentário acabou.")
    body = _text(body, "Escreva o comentário.")
    if body != comment.body:
        add_event(
            db,
            ticket,
            "comment.edited",
            auth,
            comment_id=str(comment.public_id),
            before=comment.body,
        )
        comment.body = body
        comment.edited_at = func.now()
    await _add_watchers(db, auth, ticket, mention_ids, "mentioned")
    await db.commit()
    await db.refresh(comment)
    return comment


async def assign(db: AsyncSession, auth: Auth, ticket: Ticket, assignee: Assignee) -> None:
    """Assumir, atribuir a outro membro (supervisor) ou devolver à fila (docs/08 §8.5)."""
    new: User | None
    if assignee == "me" or assignee == auth.user.public_id:
        require(auth, ticket, "assign_self")
        new = auth.user
    elif assignee is None:
        require(auth, ticket, "unassign")
        new = None
    else:
        require(auth, ticket, "assign_others")
        new = await _team_member(db, assignee, ticket.team_id)
    if (new.id if new else None) == ticket.assignee_id:
        return
    add_event(db, ticket, "ticket.assigned", auth, **{"from": ref(ticket.assignee), "to": ref(new)})
    ticket.assignee_id = new.id if new else None
    if new is not None and ticket.first_assigned_at is None:
        ticket.first_assigned_at = func.now()
    await db.commit()


async def transfer(
    db: AsyncSession, auth: Auth, ticket: Ticket, team_id: uuid.UUID, reason: str
) -> None:
    """Vai para a fila do outro grupo, sem responsável; o anterior continua vendo (docs/10)."""
    require(auth, ticket, "transfer")
    team = await _active_team(db, team_id)
    if team.id == ticket.team_id:
        raise HTTPException(422, "O chamado já está neste grupo.")
    comment = await _comment(db, auth, ticket, _text(reason, "Informe o motivo da transferência."))
    payload: dict[str, Any] = {
        "from": ref(ticket.team),
        "to": ref(team),
        "comment_id": str(comment.public_id),
    }
    if ticket.assignee is not None:
        payload["unassigned"] = ref(ticket.assignee)
    if ticket.status.kind != "open":
        status = await _default_status(db, "open")
        payload["status"] = {"from": ref(ticket.status), "to": ref(status)}
        ticket.status_id = status.id
    add_event(db, ticket, "ticket.transferred", auth, **payload)
    ticket.team_id = team.id
    ticket.assignee_id = None
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
        comment = await _comment(db, auth, ticket, text, is_solution=data.action == "close")
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
