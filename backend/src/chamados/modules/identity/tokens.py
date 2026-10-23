"""Segredos aleatórios. No banco fica só o SHA-256 (docs/09 §9.4 e §9.7). Tokens de API."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

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
    token = ApiToken(
        user=user, name=name, scope=scope, token_hash=sha256(raw), expires_at=expires_at
    )
    return raw, token


async def load_api_token(db: AsyncSession, raw: str) -> ApiToken | None:
    """Token válido: não revogado, dentro do prazo e de usuário ativo (o excluído é inativo)."""
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
    ):
        return None
    if token.last_used_at is None or t - token.last_used_at > _TOUCH_EVERY:
        token.last_used_at = t
        await db.commit()
    return token
