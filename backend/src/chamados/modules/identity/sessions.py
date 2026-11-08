"""Sessões no servidor com CSRF por token sincronizado (docs/09 §9.7)."""

from datetime import UTC, datetime, timedelta
from typing import NamedTuple

from fastapi import Request, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from chamados.config import Settings
from chamados.modules.audit.service import client_ip
from chamados.modules.identity.models import User, UserSession
from chamados.modules.identity.tokens import new_secret, sha256
from chamados.modules.organization.models import TeamMember

CSRF_HEADER = "X-CSRF-Token"
_TOUCH_EVERY = timedelta(minutes=1)


class CookieNames(NamedTuple):
    session: str
    csrf: str


def cookie_names(settings: Settings) -> CookieNames:
    """Com HTTPS, o prefixo `__Host-`: o navegador só aceita o cookie gravado pelo próprio
    endereço (Secure, Path=/, sem Domain), e outro sistema em *.empresa.com.br não consegue
    gravá-lo para o domínio inteiro. Sem HTTPS (COOKIE_SECURE=false), o navegador o recusaria:
    os nomes ficam sem o prefixo."""
    prefix = "__Host-" if settings.cookie_secure else ""
    return CookieNames(f"{prefix}tf_sessao", f"{prefix}tf_csrf")


def now() -> datetime:
    return datetime.now(UTC)


async def create_session(
    db: AsyncSession, user: User, request: Request, response: Response, settings: Settings
) -> UserSession:
    token, token_hash = new_secret()
    csrf, csrf_hash = new_secret()
    session = UserSession(
        user_id=user.id,
        token_hash=token_hash,
        csrf_token_hash=csrf_hash,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
        expires_at=now() + timedelta(days=settings.session_max_days),
    )
    db.add(session)
    max_age = settings.session_max_days * 86400
    common = {"max_age": max_age, "secure": settings.cookie_secure, "samesite": "lax", "path": "/"}
    names = cookie_names(settings)
    response.set_cookie(names.session, token, httponly=True, **common)  # type: ignore[arg-type]
    # O JavaScript não lê o CSRF do cookie: a página o traz (<meta name="csrf"> e os formulários).
    response.set_cookie(names.csrf, csrf, httponly=True, **common)  # type: ignore[arg-type]
    return session


def clear_cookies(response: Response, settings: Settings) -> None:
    for name in cookie_names(settings):
        response.delete_cookie(name, path="/", secure=settings.cookie_secure, samesite="lax")


async def load_session(db: AsyncSession, token: str, settings: Settings) -> UserSession | None:
    """Sessão válida: não revogada, dentro do prazo, ativa nas últimas horas e de usuário ativo."""
    session = await db.scalar(
        select(UserSession)
        .where(UserSession.token_hash == sha256(token))
        # Os grupos (com nome, para o de clientes) já vêm aqui: get_auth monta o Actor com eles.
        .options(
            joinedload(UserSession.user).selectinload(User.memberships).joinedload(TeamMember.team)
        )
    )
    t = now()
    if (
        session is None
        or session.revoked_at is not None
        or session.expires_at <= t
        or session.last_seen_at + timedelta(hours=settings.session_idle_hours) <= t
        or not session.user.is_active
    ):
        return None
    if t - session.last_seen_at > _TOUCH_EVERY:
        session.last_seen_at = t
        await db.commit()
    return session


def csrf_ok(session: UserSession, header: str | None) -> bool:
    return header is not None and sha256(header) == session.csrf_token_hash


async def revoke_sessions(db: AsyncSession, user_id: int, keep_id: int | None = None) -> None:
    stmt = (
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now())
    )
    if keep_id is not None:
        stmt = stmt.where(UserSession.id != keep_id)
    await db.execute(stmt)
