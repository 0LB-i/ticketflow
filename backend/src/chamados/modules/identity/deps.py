"""Dependências de autenticação e autorização das rotas."""

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from chamados.config import Settings
from chamados.core.permissions import Actor, P, can
from chamados.db.session import DB
from chamados.modules.identity.models import User, UserSession
from chamados.modules.identity.sessions import CSRF_HEADER, SESSION_COOKIE, csrf_ok, load_session

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


@dataclass
class Auth:
    user: User
    session: UserSession
    actor: Actor


async def get_auth(request: Request, db: DB, settings: SettingsDep) -> Auth:
    token = request.cookies.get(SESSION_COOKIE)
    session = await load_session(db, token, settings) if token else None
    if session is None:
        raise HTTPException(401, "Sessão expirada ou inexistente. Entre novamente.")
    if request.method in UNSAFE and not csrf_ok(session, request.headers.get(CSRF_HEADER)):
        raise HTTPException(403, "Token CSRF ausente ou inválido.")
    # Papel e grupos lidos a cada requisição: mudanças valem na hora (docs/09 §9.7).
    user = await db.scalar(
        select(User).where(User.id == session.user_id).options(selectinload(User.memberships))
    )
    if user is None:
        raise HTTPException(401, "Sessão expirada ou inexistente. Entre novamente.")
    actor = Actor(
        user_id=user.id,
        role=user.role.code,
        teams=frozenset(m.team_id for m in user.memberships),
        supervises=frozenset(m.team_id for m in user.memberships if m.role == "supervisor"),
    )
    return Auth(user=user, session=session, actor=actor)


CurrentAuth = Annotated[Auth, Depends(get_auth)]


def require(permission: P) -> Callable[[Auth], Coroutine[Any, Any, Auth]]:
    async def dependency(auth: CurrentAuth) -> Auth:
        if not can(auth.actor, permission):
            raise HTTPException(403, "Você não tem permissão para esta ação.")
        return auth

    return dependency
