"""Dependências de autenticação e autorização das rotas."""

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request

from chamados.config import Settings
from chamados.core.permissions import CLIENT_MANAGERS_TEAM, Actor, P, can
from chamados.db.session import DB
from chamados.modules.identity.models import ApiToken, User, UserSession
from chamados.modules.identity.sessions import CSRF_HEADER, SESSION_COOKIE, csrf_ok, load_session
from chamados.modules.identity.tokens import load_api_token

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
# Com a senha provisória, só isto funciona até a troca (docs/09 §9.2).
ALLOWED_BEFORE_PASSWORD_CHANGE = {
    ("GET", "/api/v1/me"),
    ("POST", "/api/v1/me/password"),
    ("POST", "/api/v1/auth/logout"),
}


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


@dataclass
class Auth:
    """Quem fez a requisição. Pela interface há uma sessão; por um token de API, o token. Os
    services só usam `user` e `actor`."""

    user: User
    actor: Actor
    session: UserSession | None = None
    token: ApiToken | None = None


async def get_auth(request: Request, db: DB, settings: SettingsDep) -> Auth:
    if (authorization := request.headers.get("authorization")) is not None:
        return await _token_auth(request, db, authorization)
    token = request.cookies.get(SESSION_COOKIE)
    session = await load_session(db, token, settings) if token else None
    if session is None:
        raise HTTPException(401, "Sessão expirada ou inexistente. Entre novamente.")
    if request.method in UNSAFE and not csrf_ok(session, request.headers.get(CSRF_HEADER)):
        raise HTTPException(403, "Token CSRF ausente ou inválido.")
    if (
        session.user.must_change_password
        and (request.method, request.url.path) not in ALLOWED_BEFORE_PASSWORD_CHANGE
    ):
        raise HTTPException(403, "Troque a senha provisória antes de continuar.")
    return session_auth(session)


async def _token_auth(request: Request, db: DB, authorization: str) -> Auth:
    """Token de API (docs/05): sem cookie, sem CSRF. O de leitura só passa em GET."""
    scheme, _, raw = authorization.partition(" ")
    token = await load_api_token(db, raw.strip()) if scheme.lower() == "bearer" else None
    if token is None:
        raise HTTPException(401, "Token de API inválido, expirado ou revogado.")
    if token.user.must_change_password:
        raise HTTPException(403, "Troque a senha provisória antes de continuar.")
    if request.method in UNSAFE and token.scope != "write":
        raise HTTPException(403, "Este token de API só permite leitura.")
    return Auth(user=token.user, actor=actor_of(token.user), token=token)


def session_auth(session: UserSession) -> Auth:
    """Usuário e Actor de uma sessão já validada (API e telas do servidor)."""
    return Auth(user=session.user, actor=actor_of(session.user), session=session)


def actor_of(user: User) -> Actor:
    # Papel e grupos lidos a cada requisição, junto com a sessão ou o token: mudanças valem na
    # hora (docs/09 §9.7).
    return Actor(
        user_id=user.id,
        role=user.role.code,
        teams=frozenset(m.team_id for m in user.memberships),
        supervises=frozenset(m.team_id for m in user.memberships if m.role == "supervisor"),
        manages_clients=any(
            m.team.is_active and m.team.name.strip().casefold() == CLIENT_MANAGERS_TEAM
            for m in user.memberships
        ),
    )


CurrentAuth = Annotated[Auth, Depends(get_auth)]


def require(permission: P) -> Callable[[Auth], Coroutine[Any, Any, Auth]]:
    async def dependency(auth: CurrentAuth) -> Auth:
        # As rotas com permissão própria (administração, auditoria, clientes) ficam fora do
        # alcance dos tokens de API, mesmo os de um administrador (docs/05).
        if auth.token is not None:
            raise HTTPException(403, "Tokens de API não acessam a administração.")
        if not can(auth.actor, permission):
            raise HTTPException(403, "Você não tem permissão para esta ação.")
        return auth

    return dependency


def require_session(auth: Auth) -> UserSession:
    """A sessão da interface, para o que só faz sentido nela (sair, trocar a senha)."""
    if auth.session is None:
        raise HTTPException(403, "Esta ação só pode ser feita pela interface.")
    return auth.session
