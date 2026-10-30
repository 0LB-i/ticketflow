"""Grupos (docs/08, docs/13: /admin/grupos).

Listar exige estar logado (os formulários de chamado usam as listas). Alterar exige
admin.organization.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from chamados.core.permissions import CLIENT_ROLE, P, can
from chamados.db.session import DB
from chamados.modules.audit.service import record
from chamados.modules.identity.deps import Auth, CurrentAuth, require
from chamados.modules.identity.models import User
from chamados.modules.organization.models import Team, TeamMember
from chamados.modules.tickets import service as tickets

router = APIRouter(tags=["organização"])
Admin = Annotated[Auth, Depends(require(P.ADMIN_ORGANIZATION))]
MemberRole = Literal["member", "supervisor"]
Notify = Literal["queue_only", "email_all_members"]


# --- grupos -------------------------------------------------------------------------------


class MemberOut(BaseModel):
    user_id: uuid.UUID
    display_name: str
    email: str | None = Field(description="só para quem administra os grupos; os demais: nulo")
    role: MemberRole
    is_active: bool


class TeamOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    notify_on_new: Notify
    is_active: bool
    members: list[MemberOut]


class TeamList(BaseModel):
    items: list[TeamOut]


class TeamCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    notify_on_new: Notify = "queue_only"


class TeamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    notify_on_new: Notify | None = None
    is_active: bool | None = None


class MemberIn(BaseModel):
    role: MemberRole = "member"


_TEAM_LOAD = selectinload(Team.members).selectinload(TeamMember.user)


def _team_out(team: Team, *, emails: bool = True) -> TeamOut:
    """`emails`: a lista de grupos é lida por todos (formulários de chamado), que só precisam
    dos nomes; o e-mail de cada pessoa fica para quem administra os grupos."""
    return TeamOut(
        id=team.public_id,
        name=team.name,
        description=team.description,
        notify_on_new=team.notify_on_new,
        is_active=team.is_active,
        members=[
            MemberOut(
                user_id=m.user.public_id,
                display_name=m.user.display_name,
                email=m.user.email if emails else None,
                role=m.role,
                is_active=m.user.is_active,
            )
            for m in sorted(
                team.members, key=lambda m: (m.role != "supervisor", m.user.display_name)
            )
        ],
    )


def _team_snapshot(team: Team) -> dict[str, object]:
    return {
        "name": team.name,
        "description": team.description,
        "notify_on_new": team.notify_on_new,
        "is_active": team.is_active,
    }


async def _team(db: AsyncSession, team_id: uuid.UUID) -> Team:
    team = await db.scalar(select(Team).where(Team.public_id == team_id).options(_TEAM_LOAD))
    if team is None:
        raise HTTPException(404, "Grupo não encontrado.")
    return team


async def _name_taken(db: AsyncSession, name: str, except_id: int | None = None) -> bool:
    stmt = select(Team.id).where(Team.name == name)
    if except_id is not None:
        stmt = stmt.where(Team.id != except_id)
    return (await db.scalar(stmt)) is not None


@router.get("/teams", response_model=TeamList)
async def list_teams(auth: CurrentAuth, db: DB) -> TeamList:
    teams = (await db.scalars(select(Team).options(_TEAM_LOAD).order_by(Team.name))).all()
    # Os e-mails dos membros são da administração: nunca para um token de API (docs/05).
    emails = auth.token is None and can(auth.actor, P.ADMIN_ORGANIZATION)
    return TeamList(items=[_team_out(t, emails=emails) for t in teams])


@router.post("/teams", response_model=TeamOut, status_code=201)
async def create_team(data: TeamCreate, auth: Admin, request: Request, db: DB) -> TeamOut:
    name = data.name.strip()
    if await _name_taken(db, name):
        raise HTTPException(409, "Já existe um grupo com este nome.")
    team = Team(name=name, description=data.description, notify_on_new=data.notify_on_new)
    db.add(team)
    await db.flush()
    record(
        db,
        "team.created",
        request=request,
        actor_user_id=auth.user.id,
        target_type="team",
        target_id=team.public_id,
        after=_team_snapshot(team),
    )
    await db.commit()
    return _team_out(await _team(db, team.public_id))


@router.patch("/teams/{team_id}", response_model=TeamOut)
async def update_team(
    team_id: uuid.UUID, data: TeamUpdate, auth: Admin, request: Request, db: DB
) -> TeamOut:
    team = await _team(db, team_id)
    before = _team_snapshot(team)
    # Nulo só apaga a descrição; nos outros campos vale como não enviado.
    changes = {
        k: v
        for k, v in data.model_dump(exclude_unset=True).items()
        if v is not None or k == "description"
    }
    if "name" in changes:
        changes["name"] = changes["name"].strip()
        if await _name_taken(db, changes["name"], team.id):
            raise HTTPException(409, "Já existe um grupo com este nome.")
    for field, value in changes.items():
        setattr(team, field, value)
    if _team_snapshot(team) != before:
        record(
            db,
            "team.updated",
            request=request,
            actor_user_id=auth.user.id,
            target_type="team",
            target_id=team.public_id,
            before=before,
            after=_team_snapshot(team),
        )
    await db.commit()
    return _team_out(await _team(db, team_id))


@router.put("/teams/{team_id}/members/{user_id}", response_model=TeamOut)
async def put_member(
    team_id: uuid.UUID, user_id: uuid.UUID, data: MemberIn, auth: Admin, request: Request, db: DB
) -> TeamOut:
    """Inclui o usuário no grupo ou muda o papel dele (membro / supervisor)."""
    team = await _team(db, team_id)
    # O excluído sai dos grupos e não volta (a linha fica só para o histórico).
    user = await db.scalar(select(User).where(User.public_id == user_id, User.deleted_at.is_(None)))
    if user is None:
        raise HTTPException(404, "Usuário não encontrado.")
    if user.role.code == CLIENT_ROLE:
        raise HTTPException(422, "Quem tem o papel Cliente não entra em grupos.")
    member = next((m for m in team.members if m.user_id == user.id), None)
    before = {"role": member.role} if member else None
    if member is None:
        team.members.append(TeamMember(user_id=user.id, role=data.role))
    else:
        member.role = data.role
    if before != {"role": data.role}:
        record(
            db,
            "team.member_set",
            request=request,
            actor_user_id=auth.user.id,
            target_type="team",
            target_id=team.public_id,
            before=before,
            after={"user": str(user.public_id), "role": data.role},
        )
    await db.commit()
    db.expire_all()
    return _team_out(await _team(db, team_id))


@router.delete("/teams/{team_id}/members/{user_id}", response_model=TeamOut)
async def remove_member(
    team_id: uuid.UUID, user_id: uuid.UUID, auth: Admin, request: Request, db: DB
) -> TeamOut:
    team = await _team(db, team_id)
    member = next((m for m in team.members if m.user.public_id == user_id), None)
    if member is None:
        raise HTTPException(404, "Este usuário não é membro do grupo.")
    # Os chamados abertos do grupo que eram dela passam a outro responsável ou ao supervisor.
    await tickets.release(db, auth, member.user, team.id)
    team.members.remove(member)
    record(
        db,
        "team.member_removed",
        request=request,
        actor_user_id=auth.user.id,
        target_type="team",
        target_id=team.public_id,
        before={"user": str(user_id), "role": member.role},
    )
    await db.commit()
    db.expire_all()
    return _team_out(await _team(db, team_id))
