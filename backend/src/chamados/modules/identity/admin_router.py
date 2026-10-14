"""Administração de usuários (docs/13: /admin/usuarios). Exige admin.users."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from chamados.core.permissions import P
from chamados.db.session import DB
from chamados.modules.audit.service import record
from chamados.modules.identity.deps import Auth, SettingsDep, require
from chamados.modules.identity.models import User
from chamados.modules.identity.passwords import MAX_LENGTH, hash_password, password_problem
from chamados.modules.identity.service import issue_token, link, send_link_email
from chamados.modules.identity.sessions import now, revoke_sessions
from chamados.modules.organization.models import Role, Team, TeamMember
from chamados.modules.system.service import user_locale

router = APIRouter(prefix="/users", tags=["usuários"])
Admin = Annotated[Auth, Depends(require(P.ADMIN_USERS))]
RoleCode = Literal["agent", "admin", "auditor"]


class UserTeam(BaseModel):
    id: uuid.UUID
    name: str
    role: Literal["member", "supervisor"]


class UserOut(BaseModel):
    id: uuid.UUID
    email: str | None
    username: str | None
    full_name: str
    role: RoleCode
    status: Literal["ativo", "convite_pendente", "inativo"]
    teams: list[UserTeam]
    last_login_at: datetime | None
    created_at: datetime


class UserList(BaseModel):
    items: list[UserOut]


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=200)
    role: RoleCode = "agent"
    password: str = Field(max_length=MAX_LENGTH, description="senha inicial, trocada no 1º acesso")
    team_ids: list[uuid.UUID] = Field(default=[], description="grupos em que entra como membro")


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    email: EmailStr | None = None
    role: RoleCode | None = None
    is_active: bool | None = None


class LinkOut(BaseModel):
    """`url` só vem quando não há SMTP: o admin repassa o link por outro meio."""

    purpose: Literal["invite", "password_reset"]
    sent_by_email: bool
    url: str | None = None


def _out(user: User) -> UserOut:
    status: Literal["ativo", "convite_pendente", "inativo"] = (
        "inativo"
        if not user.is_active
        else "convite_pendente"
        if not user.password_hash
        else "ativo"
    )
    return UserOut(
        id=user.public_id,
        email=user.email,
        username=user.username,
        full_name=user.full_name,
        role=user.role.code,
        status=status,
        teams=[
            UserTeam(id=m.team.public_id, name=m.team.name, role=m.role)
            for m in sorted(user.memberships, key=lambda m: m.team.name)
        ],
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


def _snapshot(user: User) -> dict[str, object]:
    return {
        "email": user.email,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role.code,
        "is_active": user.is_active,
    }


_LOAD = selectinload(User.memberships).selectinload(TeamMember.team)


async def _get(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.scalar(select(User).where(User.public_id == user_id).options(_LOAD))
    if user is None:
        raise HTTPException(404, "Usuário não encontrado.")
    return user


async def _role(db: AsyncSession, code: str) -> Role:
    role = await db.scalar(select(Role).where(Role.code == code))
    if role is None:
        raise HTTPException(422, "Papel inválido.")
    return role


async def _send_link(
    request: Request, db: AsyncSession, settings: SettingsDep, tasks: BackgroundTasks, user: User
) -> LinkOut:
    purpose: Literal["invite", "password_reset"] = (
        "password_reset" if user.password_hash else "invite"
    )
    mailer = request.app.state.mailer
    if user.email is None and mailer.configured:
        raise HTTPException(409, "Cadastre um e-mail para este usuário antes de enviar o link.")
    raw = await issue_token(db, user, purpose)
    url = link(settings, purpose, raw)
    tasks.add_task(send_link_email, mailer, user, purpose, url, await user_locale(db, user))
    return LinkOut(
        purpose=purpose, sent_by_email=mailer.configured, url=None if mailer.configured else url
    )


@router.get("", response_model=UserList)
async def list_users(_: Admin, db: DB) -> UserList:
    users = (await db.scalars(select(User).options(_LOAD).order_by(User.full_name))).all()
    return UserList(items=[_out(u) for u in users])


@router.get("/{user_id}", response_model=UserOut)
async def get_user(user_id: uuid.UUID, _: Admin, db: DB) -> UserOut:
    return _out(await _get(db, user_id))


@router.post("", response_model=UserOut, status_code=201)
async def create_user(data: UserCreate, auth: Admin, request: Request, db: DB) -> UserOut:
    """Cria com a senha inicial definida pelo admin; a pessoa troca no primeiro acesso."""
    if await db.scalar(select(User.id).where(User.email == data.email)):
        raise HTTPException(409, "Já existe um usuário com este e-mail.")
    if problem := password_problem(data.password, data.email):
        raise HTTPException(422, problem)
    teams = (
        await db.scalars(select(Team).where(Team.public_id.in_(data.team_ids), Team.is_active))
    ).all()
    if len(teams) != len(set(data.team_ids)):
        raise HTTPException(422, "Grupo não encontrado ou inativo.")
    user = User(
        email=data.email,
        full_name=data.full_name.strip(),
        role=await _role(db, data.role),
        password_hash=await run_in_threadpool(hash_password, data.password),
        password_changed_at=now(),
        must_change_password=True,
        memberships=[TeamMember(team=t, role="member") for t in teams],
    )
    db.add(user)
    await db.flush()
    record(
        db,
        "user.created",
        request=request,
        actor_user_id=auth.user.id,
        target_type="user",
        target_id=user.public_id,
        after=_snapshot(user),
    )
    for team in teams:
        record(
            db,
            "team.member_set",
            request=request,
            actor_user_id=auth.user.id,
            target_type="team",
            target_id=team.public_id,
            before=None,
            after={"user": str(user.public_id), "role": "member"},
        )
    await db.commit()
    return _out(await _get(db, user.public_id))


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID, data: UserUpdate, auth: Admin, request: Request, db: DB
) -> UserOut:
    user = await _get(db, user_id)
    before = _snapshot(user)
    losing_admin = user.role.code == "admin" and (
        (data.role is not None and data.role != "admin") or data.is_active is False
    )
    if losing_admin:
        admins = await db.scalar(
            select(func.count())
            .select_from(User)
            .join(Role)
            .where(Role.code == "admin", User.is_active)
        )
        if (admins or 0) <= 1:
            raise HTTPException(409, "O sistema precisa de pelo menos um administrador ativo.")
    if data.full_name is not None:
        user.full_name = data.full_name.strip()
    if data.email is not None and data.email != user.email:
        taken = await db.scalar(select(User.id).where(User.email == data.email, User.id != user.id))
        if taken:
            raise HTTPException(409, "Já existe um usuário com este e-mail.")
        user.email = data.email
    if data.role is not None:
        user.role = await _role(db, data.role)
    if data.is_active is not None and data.is_active != user.is_active:
        user.is_active = data.is_active
        if not data.is_active:
            await revoke_sessions(db, user.id)  # docs/09 §9.3: sessões encerradas na hora
    after = _snapshot(user)
    if after != before:
        record(
            db,
            "user.updated",
            request=request,
            actor_user_id=auth.user.id,
            target_type="user",
            target_id=user.public_id,
            before=before,
            after=after,
        )
    await db.commit()
    return _out(await _get(db, user_id))


@router.post("/{user_id}/link", response_model=LinkOut)
async def send_access_link(
    user_id: uuid.UUID,
    auth: Admin,
    request: Request,
    db: DB,
    settings: SettingsDep,
    tasks: BackgroundTasks,
) -> LinkOut:
    """Reenvia o convite (quem ainda não tem senha) ou envia um link de redefinição."""
    user = await _get(db, user_id)
    if not user.is_active:
        raise HTTPException(409, "Usuário inativo. Reative antes de enviar o link.")
    sent = await _send_link(request, db, settings, tasks, user)
    record(
        db,
        f"user.{sent.purpose}_link_sent",
        request=request,
        actor_user_id=auth.user.id,
        target_type="user",
        target_id=user.public_id,
    )
    await db.commit()
    return sent
