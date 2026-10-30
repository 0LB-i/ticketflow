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
# "Esqueci a senha": um link por conta neste intervalo (o anterior continua valendo). Sem isso,
# qualquer um encheria a caixa de e-mail da pessoa com pedidos.
RESET_EVERY = timedelta(minutes=5)


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


async def recently_issued(
    db: AsyncSession, user: User, purpose: Purpose, within: timedelta
) -> bool:
    """Há um token deste tipo, ainda não usado, emitido há menos de `within`?"""
    found = await db.scalar(
        select(AuthToken.id).where(
            AuthToken.user_id == user.id,
            AuthToken.purpose == purpose,
            AuthToken.used_at.is_(None),
            AuthToken.created_at > now() - within,
        )
    )
    return found is not None


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


# Textos dos e-mails por idioma (core/i18n.py). {nome}: primeiro nome; {url}: link.
EMAILS: dict[str, dict[str, tuple[str, str]]] = {
    "pt-BR": {
        "invite": (
            "Seu acesso ao TicketFlow",
            "Olá, {nome}.\n\n"
            "Você foi cadastrado no TicketFlow, o sistema de chamados da equipe.\n"
            "Para criar sua senha, acesse o link abaixo (válido por 72 horas):\n\n{url}\n\n"
            "Se você não esperava este convite, ignore este e-mail.",
        ),
        "password_reset": (
            "Redefinição de senha do TicketFlow",
            "Olá, {nome}.\n\n"
            "Recebemos um pedido para redefinir sua senha do TicketFlow.\n"
            "Para criar uma senha nova, acesse o link abaixo (válido por 30 minutos):\n\n"
            "{url}\n\n"
            "Se não foi você, ignore este e-mail: sua senha continua a mesma.",
        ),
        "locked": (
            "Sua conta do TicketFlow foi bloqueada por 15 minutos",
            "Olá, {nome}.\n\n"
            "Houve 10 tentativas de entrar na sua conta com a senha errada, vindas do mesmo "
            "endereço, então ela foi bloqueada por 15 minutos para esse endereço; dos outros, ela "
            "continua funcionando.\n\nSe não foi você, avise o "
            "administrador do sistema e troque sua senha.",
        ),
    },
    "en": {
        "invite": (
            "Your TicketFlow access",
            "Hello, {nome}.\n\n"
            "You have been added to TicketFlow, the team's ticket system.\n"
            "To create your password, open the link below (valid for 72 hours):\n\n{url}\n\n"
            "If you were not expecting this invitation, ignore this email.",
        ),
        "password_reset": (
            "TicketFlow password reset",
            "Hello, {nome}.\n\n"
            "We received a request to reset your TicketFlow password.\n"
            "To create a new password, open the link below (valid for 30 minutes):\n\n"
            "{url}\n\n"
            "If it wasn't you, ignore this email: your password stays the same.",
        ),
        "locked": (
            "Your TicketFlow account was locked for 15 minutes",
            "Hello, {nome}.\n\n"
            "There were 10 failed sign-in attempts on your account from the same address, so it "
            "was locked for 15 minutes for that address; from other "
            "addresses it still works.\n\nIf it wasn't you, tell the system administrator and "
            "change your password.",
        ),
    },
}


def _send(mailer: Mailer, user: User, kind: str, locale: str, url: str = "") -> None:
    if user.email is None:
        return
    subject, body = EMAILS.get(locale, EMAILS["pt-BR"])[kind]
    mailer.send(user.email, subject, body.format(nome=user.display_name.split()[0], url=url))


def send_link_email(mailer: Mailer, user: User, purpose: Purpose, url: str, locale: str) -> None:
    _send(mailer, user, purpose, locale, url)


def send_locked_email(mailer: Mailer, user: User, locale: str) -> None:
    _send(mailer, user, "locked", locale)
