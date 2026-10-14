"""Categorias, status e códigos de resolução (docs/13: /admin/categorias).

Listar exige estar logado (o formulário de chamado usa as listas). Alterar categorias exige
admin.catalog; criar, renomear, ordenar e remover status exige admin.settings (a tela fica em
Configurações). Códigos de resolução personalizados ficam para a Sprint 5.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from chamados.core.permissions import P
from chamados.db.session import DB
from chamados.modules.audit.service import record
from chamados.modules.catalog.models import Category, ResolutionCode, TicketStatus
from chamados.modules.identity.deps import Auth, CurrentAuth, require
from chamados.modules.organization.models import Team
from chamados.modules.tickets.models import Ticket

router = APIRouter(tags=["catálogo"])
Admin = Annotated[Auth, Depends(require(P.ADMIN_CATALOG))]
SettingsAdmin = Annotated[Auth, Depends(require(P.ADMIN_SETTINGS))]
TicketType = Literal["incident", "request", "task"]
StatusKind = Literal["approval", "open", "waiting", "closed", "canceled"]
# Aprovação entra na Fase 2: o administrador escolhe entre estes.
EditableKind = Literal["open", "waiting", "closed", "canceled"]
MAX_DEPTH = 3  # docs/08 §8.1


# --- categorias -----------------------------------------------------------------------------


class CategoryOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    parent_id: uuid.UUID | None
    default_team_id: uuid.UUID | None
    default_type: TicketType
    is_confidential: bool
    is_active: bool


class CategoryList(BaseModel):
    items: list[CategoryOut]


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    parent_id: uuid.UUID | None = None
    default_team_id: uuid.UUID | None = None
    default_type: TicketType = "incident"
    is_confidential: bool = False


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    parent_id: uuid.UUID | None = None
    default_team_id: uuid.UUID | None = None
    default_type: TicketType | None = None
    is_confidential: bool | None = None
    is_active: bool | None = None


def _snapshot(c: Category) -> dict[str, object]:
    return {
        "name": c.name,
        "description": c.description,
        "parent_id": c.parent_id,
        "default_team_id": c.default_team_id,
        "default_type": c.default_type,
        "is_confidential": c.is_confidential,
        "is_active": c.is_active,
    }


async def _all(db: AsyncSession) -> dict[int, Category]:
    return {c.id: c for c in (await db.scalars(select(Category))).all()}


def _out(c: Category, by_id: dict[int, Category]) -> CategoryOut:
    return CategoryOut(
        id=c.public_id,
        name=c.name,
        description=c.description,
        parent_id=by_id[c.parent_id].public_id if c.parent_id else None,
        default_team_id=c.default_team.public_id if c.default_team else None,
        default_type=c.default_type,
        is_confidential=c.is_confidential,
        is_active=c.is_active,
    )


def _find(by_id: dict[int, Category], public_id: uuid.UUID) -> Category:
    found = next((c for c in by_id.values() if c.public_id == public_id), None)
    if found is None:
        raise HTTPException(404, "Categoria não encontrada.")
    return found


def _depth(by_id: dict[int, Category], c: Category) -> int:
    """Nível da categoria: 1 na raiz."""
    level = 1
    while c.parent_id is not None:
        c, level = by_id[c.parent_id], level + 1
    return level


def _height(by_id: dict[int, Category], c: Category) -> int:
    """Níveis da subárvore que começa em `c` (1 se não tiver subcategorias)."""
    children = [x for x in by_id.values() if x.parent_id == c.id]
    return 1 + max((_height(by_id, x) for x in children), default=0)


async def _team_id(db: AsyncSession, public_id: uuid.UUID | None) -> int | None:
    if public_id is None:
        return None
    team_id = await db.scalar(select(Team.id).where(Team.public_id == public_id))
    if team_id is None:
        raise HTTPException(422, "Grupo padrão não encontrado.")
    return team_id


async def _check_name(
    db: AsyncSession, name: str, parent_id: int | None, except_id: int | None
) -> None:
    stmt = select(Category.id).where(
        Category.name == name, Category.parent_id.is_not_distinct_from(parent_id)
    )
    if except_id is not None:
        stmt = stmt.where(Category.id != except_id)
    # Sem autoflush: a alteração pendente violaria a constraint antes da resposta 409.
    with db.no_autoflush:
        taken = await db.scalar(stmt)
    if taken:
        raise HTTPException(409, "Já existe uma categoria com este nome no mesmo nível.")


@router.get("/categories", response_model=CategoryList)
async def list_categories(_: CurrentAuth, db: DB) -> CategoryList:
    by_id = await _all(db)
    items = sorted(by_id.values(), key=lambda c: c.name.casefold())
    return CategoryList(items=[_out(c, by_id) for c in items])


@router.post("/categories", response_model=CategoryOut, status_code=201)
async def create_category(
    data: CategoryCreate, auth: Admin, request: Request, db: DB
) -> CategoryOut:
    by_id = await _all(db)
    parent = _find(by_id, data.parent_id) if data.parent_id else None
    if parent and _depth(by_id, parent) >= MAX_DEPTH:
        raise HTTPException(422, f"As categorias têm no máximo {MAX_DEPTH} níveis.")
    name = data.name.strip()
    await _check_name(db, name, parent.id if parent else None, None)
    category = Category(
        name=name,
        description=data.description,
        parent_id=parent.id if parent else None,
        default_team_id=await _team_id(db, data.default_team_id),
        default_type=data.default_type,
        is_confidential=data.is_confidential,
    )
    db.add(category)
    await db.flush()
    record(
        db,
        "category.created",
        request=request,
        actor_user_id=auth.user.id,
        target_type="category",
        target_id=category.public_id,
        after=_snapshot(category),
    )
    await db.commit()
    await db.refresh(category, ["default_team"])
    by_id[category.id] = category
    return _out(category, by_id)


@router.patch("/categories/{category_id}", response_model=CategoryOut)
async def update_category(
    category_id: uuid.UUID, data: CategoryUpdate, auth: Admin, request: Request, db: DB
) -> CategoryOut:
    by_id = await _all(db)
    category = _find(by_id, category_id)
    before = _snapshot(category)
    changes = data.model_dump(exclude_unset=True)
    if "parent_id" in changes:
        parent = _find(by_id, changes["parent_id"]) if changes["parent_id"] else None
        # Sem ciclos: a nova categoria acima não pode ser a própria nem uma subcategoria dela.
        ancestor = parent
        while ancestor is not None:
            if ancestor.id == category.id:
                raise HTTPException(422, "Uma categoria não pode ficar abaixo dela mesma.")
            ancestor = by_id[ancestor.parent_id] if ancestor.parent_id else None
        if (_depth(by_id, parent) if parent else 0) + _height(by_id, category) > MAX_DEPTH:
            raise HTTPException(422, f"As categorias têm no máximo {MAX_DEPTH} níveis.")
        category.parent_id = parent.id if parent else None
    if "default_team_id" in changes:
        category.default_team_id = await _team_id(db, changes["default_team_id"])
    if changes.get("name") is not None:
        category.name = changes["name"].strip()
    if "description" in changes:
        category.description = changes["description"]
    for field in ("default_type", "is_confidential", "is_active"):
        if changes.get(field) is not None:
            setattr(category, field, changes[field])
    await _check_name(db, category.name, category.parent_id, category.id)
    if _snapshot(category) != before:
        record(
            db,
            "category.updated",
            request=request,
            actor_user_id=auth.user.id,
            target_type="category",
            target_id=category.public_id,
            before=before,
            after=_snapshot(category),
        )
    await db.commit()
    await db.refresh(category, ["default_team"])
    return _out(category, by_id)


# --- status e códigos de resolução ------------------------------------------------------------


class StatusOut(BaseModel):
    id: int
    name: str
    kind: StatusKind
    is_default: bool = Field(description="usado quando o fluxo leva a este kind")
    is_review: bool = Field(description='revisão do supervisor ("Entregue")')
    ticket_count: int


class StatusList(BaseModel):
    items: list[StatusOut]


StatusName = Annotated[str, Field(min_length=1, max_length=50)]


class StatusCreate(BaseModel):
    name: StatusName
    kind: EditableKind


class StatusUpdate(BaseModel):
    name: StatusName


class StatusOrder(BaseModel):
    ids: list[int] = Field(description="todos os status, na nova ordem")


class ResolutionCodeOut(BaseModel):
    id: int
    name: str
    is_active: bool


class ResolutionCodeList(BaseModel):
    items: list[ResolutionCodeOut]


async def _statuses(db: AsyncSession) -> StatusList:
    counts = dict(
        (await db.execute(select(Ticket.status_id, func.count()).group_by(Ticket.status_id))).all()
    )
    rows = await db.scalars(select(TicketStatus).order_by(TicketStatus.sort_order, TicketStatus.id))
    return StatusList(
        items=[
            StatusOut(
                id=s.id,
                name=s.name,
                kind=s.kind,
                is_default=s.is_default_for_kind,
                is_review=s.is_review,
                ticket_count=counts.get(s.id, 0),
            )
            for s in rows
        ]
    )


async def _status(db: AsyncSession, status_id: int) -> TicketStatus:
    status = await db.get(TicketStatus, status_id)
    if status is None:
        raise HTTPException(404, "Status não encontrado.")
    return status


async def _check_status_name(db: AsyncSession, name: str, except_id: int | None = None) -> str:
    name = name.strip()
    if not name:
        raise HTTPException(422, "Informe o nome do status.")
    found = await db.scalar(
        select(TicketStatus.id).where(func.lower(TicketStatus.name) == name.lower())
    )
    if found is not None and found != except_id:
        raise HTTPException(422, "Já existe um status com este nome.")
    return name


@router.get("/statuses", response_model=StatusList)
async def list_statuses(_: CurrentAuth, db: DB) -> StatusList:
    return await _statuses(db)


@router.post("/statuses", response_model=StatusList, status_code=201)
async def create_status(
    data: StatusCreate, auth: SettingsAdmin, request: Request, db: DB
) -> StatusList:
    """O novo status entra no fim da lista. O primeiro de um kind vira o padrão dele."""
    name = await _check_status_name(db, data.name)
    last = await db.scalar(select(func.max(TicketStatus.sort_order))) or 0
    has_kind = await db.scalar(
        select(TicketStatus.id).where(TicketStatus.kind == data.kind).limit(1)
    )
    status = TicketStatus(
        name=name, kind=data.kind, sort_order=last + 1, is_default_for_kind=has_kind is None
    )
    db.add(status)
    await db.flush()
    record(
        db,
        "ticket_status.created",
        request=request,
        actor_user_id=auth.user.id,
        target_type="ticket_status",
        target_id=status.id,
        after={"name": name, "kind": data.kind},
    )
    await db.commit()
    return await _statuses(db)


@router.patch("/statuses/{status_id}", response_model=StatusList)
async def update_status(
    status_id: int, data: StatusUpdate, auth: SettingsAdmin, request: Request, db: DB
) -> StatusList:
    """Só o nome muda: trocar o kind mudaria o sentido dos chamados que já estão nele."""
    status = await _status(db, status_id)
    name = await _check_status_name(db, data.name, status.id)
    if name != status.name:
        record(
            db,
            "ticket_status.updated",
            request=request,
            actor_user_id=auth.user.id,
            target_type="ticket_status",
            target_id=status.id,
            before={"name": status.name},
            after={"name": name},
        )
        status.name = name
        await db.commit()
    return await _statuses(db)


@router.put("/statuses/order", response_model=StatusList)
async def reorder_statuses(data: StatusOrder, auth: SettingsAdmin, db: DB) -> StatusList:
    statuses = {s.id: s for s in await db.scalars(select(TicketStatus))}
    if sorted(data.ids) != sorted(statuses):
        raise HTTPException(422, "Envie todos os status, cada um uma vez.")
    for position, status_id in enumerate(data.ids, start=1):
        statuses[status_id].sort_order = position
    await db.commit()
    return await _statuses(db)


@router.delete("/statuses/{status_id}", response_model=StatusList)
async def delete_status(
    status_id: int, auth: SettingsAdmin, request: Request, db: DB
) -> StatusList:
    """Cada kind precisa de um status. Os chamados no status removido vão para o padrão do kind;
    se o removido era o padrão, o próximo do mesmo kind (na ordem da lista) passa a ser."""
    status = await _status(db, status_id)
    same_kind = (
        await db.scalars(
            select(TicketStatus)
            .where(TicketStatus.kind == status.kind, TicketStatus.id != status.id)
            .order_by(TicketStatus.sort_order, TicketStatus.id)
        )
    ).all()
    if not same_kind:
        raise HTTPException(
            422, "Este é o único status com este comportamento. Crie outro antes de remover."
        )
    target = next((s for s in same_kind if s.is_default_for_kind), same_kind[0])
    if status.is_default_for_kind:
        status.is_default_for_kind = False
        await db.flush()  # o índice único aceita um padrão por kind
        target.is_default_for_kind = True
    moved = await db.scalar(select(func.count()).where(Ticket.status_id == status.id))
    await db.execute(
        update(Ticket).where(Ticket.status_id == status.id).values(status_id=target.id)
    )
    record(
        db,
        "ticket_status.deleted",
        request=request,
        actor_user_id=auth.user.id,
        target_type="ticket_status",
        target_id=status.id,
        before={"name": status.name, "kind": status.kind},
        after={"tickets_moved_to": target.name, "tickets_moved": moved},
    )
    await db.delete(status)
    await db.commit()
    return await _statuses(db)


@router.get("/resolution-codes", response_model=ResolutionCodeList)
async def list_resolution_codes(_: CurrentAuth, db: DB) -> ResolutionCodeList:
    rows = await db.scalars(select(ResolutionCode).order_by(ResolutionCode.id))
    return ResolutionCodeList(
        items=[ResolutionCodeOut(id=r.id, name=r.name, is_active=r.is_active) for r in rows]
    )
