"""Convites e redefinição de senha (docs/09 §9.4)."""

from datetime import timedelta
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from chamados.config import Settings
from chamados.modules.identity.models import AuthToken, User
from chamados.modules.identity.sessions import now
from chamados.modules.identity.tokens import new_secret, sha256
from chamados.modules.notifications.email import Mailer

Purpose = Literal["invite", "password_reset"]

VALIDITY = {"invite": timedelta(hours=72), "password_reset": timedelta(minutes=30)}
PATHS = {"invite": "convite", "password_reset": "redefinir-senha"}


async def issue_token(
    db: AsyncSession, user: User, purpose: Purpose, validity: timedelta | None = None
) -> str:
    """Cria um token de uso único e invalida os anteriores do mesmo tipo. Devolve o valor."""
    await db.execute(
        delete(AuthToken).where(
            AuthToken.user_id == user.id, AuthToken.purpose == purpose, AuthToken.used_at.is_(None)
        )
    )
    raw, token_hash = new_secret()
    db.add(
        AuthToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=token_hash,
            expires_at=now() + (validity or VALIDITY[purpose]),
        )
    )
    return raw


def link(settings: Settings, purpose: Purpose, raw: str) -> str:
    return f"{settings.app_base_url.rstrip('/')}/{PATHS[purpose]}/{raw}"


async def find_token(db: AsyncSession, raw: str) -> AuthToken | None:
    """Token válido (não usado, no prazo, de usuário ativo)."""
    token = await db.scalar(select(AuthToken).where(AuthToken.token_hash == sha256(raw)))
    if (
        token is None
        or token.used_at is not None
        or token.expires_at <= now()
        or not token.user.is_active
    ):
        return None
    return token


def send_link_email(mailer: Mailer, user: User, purpose: Purpose, url: str) -> None:
    if user.email is None:
        return
    first_name = user.full_name.split()[0]
    if purpose == "invite":
        subject = "Seu acesso ao TicketFlow"
        body = (
            f"Olá, {first_name}.\n\n"
            "Você foi cadastrado no TicketFlow, o sistema de chamados da equipe.\n"
            f"Para criar sua senha, acesse o link abaixo (válido por 72 horas):\n\n{url}\n\n"
            "Se você não esperava este convite, ignore este e-mail."
        )
    else:
        subject = "Redefinição de senha do TicketFlow"
        body = (
            f"Olá, {first_name}.\n\n"
            "Recebemos um pedido para redefinir sua senha do TicketFlow.\n"
            f"Para criar uma senha nova, acesse o link abaixo (válido por 30 minutos):\n\n{url}\n\n"
            "Se não foi você, ignore este e-mail: sua senha continua a mesma."
        )
    mailer.send(user.email, subject, body)


def send_locked_email(mailer: Mailer, user: User) -> None:
    if user.email is None:
        return
    mailer.send(
        user.email,
        "Sua conta do TicketFlow foi bloqueada por 15 minutos",
        f"Olá, {user.full_name.split()[0]}.\n\n"
        "Houve 10 tentativas seguidas de entrar na sua conta com a senha errada, então ela foi "
        "bloqueada por 15 minutos.\n\nSe não foi você, avise o administrador do sistema e, "
        "depois do bloqueio, troque sua senha.",
    )
