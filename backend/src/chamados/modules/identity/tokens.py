"""Segredos aleatórios. No banco fica só o SHA-256 (docs/09 §9.4 e §9.7). Tokens de API."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from chamados.core.permissions import CLIENT_ROLE
from chamados.modules.audit.service import record
from chamados.modules.identity.models import ApiToken, User
from chamados.modules.organization.models import TeamMember

# Prefixo dos tokens de API: fácil de reconhecer num log ou num arquivo de configuração.
API_TOKEN_PREFIX = "tf_"  # noqa: S105 (só o prefixo, não é segredo)
_TOUCH_EVERY = timedelta(minutes=1)


def new_secret() -> tuple[str, str]:
    """(valor para o cliente, hash para o banco). 256 bits de entropia."""
    raw = secrets.token_urlsafe(32)
    return raw, sha256(raw)


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_api_token(
    user: User, name: str, scope: str, expires_at: datetime | None
) -> tuple[str, ApiToken]:
    """(valor mostrado uma vez só, token para gravar)."""
    raw = API_TOKEN_PREFIX + secrets.token_urlsafe(32)
    # O id já na criação: a auditoria o grava antes do flush.
    token = ApiToken(
        public_id=uuid.uuid4(),
        user=user,
        name=name,
        scope=scope,
        token_hash=sha256(raw),
        expires_at=expires_at,
    )
    return raw, token


async def load_api_token(db: AsyncSession, raw: str) -> ApiToken | None:
    """Token válido: não revogado, dentro do prazo e de usuário ativo (o excluído é inativo) e
    que não seja do papel Cliente."""
    if not raw.startswith(API_TOKEN_PREFIX):
        return None
    token = await db.scalar(
        select(ApiToken)
        .where(ApiToken.token_hash == sha256(raw))
        # Os grupos (com nome, para o de clientes), como na sessão: o Actor é montado com eles.
        .options(
            joinedload(ApiToken.user).selectinload(User.memberships).joinedload(TeamMember.team)
        )
    )
    t = datetime.now(UTC)
    if (
        token is None
        or token.revoked_at is not None
        or (token.expires_at is not None and token.expires_at <= t)
        or not token.user.is_active
        # O papel Cliente não usa a API nem o MCP: um token de antes da troca de papel não vale.
        or token.user.role.code == CLIENT_ROLE
    ):
        return None
    if token.last_used_at is None or t - token.last_used_at > _TOUCH_EVERY:
        token.last_used_at = t
        await db.commit()
    return token


def issue_api_token(
    db: AsyncSession,
    user: User,
    name: str,
    scope: str,
    days: int | None,
    *,
    actor_user_id: int | None,
    request: Request | None = None,
    via: str | None = None,
) -> tuple[str, ApiToken]:
    """Cria o token (validade em dias; None, sem validade) e grava na auditoria; o commit fica com
    quem chama. O valor só existe aqui: no banco fica o hash."""
    expires_at = datetime.now(UTC) + timedelta(days=days) if days else None
    raw, token = new_api_token(user, name, scope, expires_at)
    db.add(token)
    after = {
        "token": str(token.public_id),
        "name": name,
        "scope": scope,
        "expires_at": expires_at.isoformat() if expires_at else None,
    }
    record(
        db,
        "api_token.created",
        request=request,
        actor_user_id=actor_user_id,
        target_type="user",
        target_id=user.public_id,
        after=after | ({"via": via} if via else {}),
    )
    return raw, token


def revoke_api_token(
    db: AsyncSession,
    token: ApiToken,
    *,
    actor_user_id: int | None,
    request: Request | None = None,
    via: str | None = None,
) -> None:
    token.revoked_at = datetime.now(UTC)
    record(
        db,
        "api_token.revoked",
        request=request,
        actor_user_id=actor_user_id,
        target_type="user",
        target_id=token.user.public_id,
        after={"token": str(token.public_id), "name": token.name} | ({"via": via} if via else {}),
    )


async def revoke_user_api_tokens(
    db: AsyncSession, user: User, *, actor_user_id: int | None, request: Request | None = None
) -> None:
    """Todos os tokens ativos da pessoa (desativada ou excluída): reativar a conta não traz de
    volta um token que pode ter vazado. O commit fica com quem chama."""
    tokens = await db.scalars(
        select(ApiToken).where(ApiToken.user_id == user.id, ApiToken.revoked_at.is_(None))
    )
    for token in tokens:
        revoke_api_token(db, token, actor_user_id=actor_user_id, request=request)
