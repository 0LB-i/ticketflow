"""Regras do chat do WhatsApp: quem vê cada número, o envio (com o nome de quem respondeu), o que
chega da ponte (ingest) e a administração dos números.

Acesso: os membros do grupo do número veem e respondem todas as conversas dele. Os responsáveis
(`whatsapp_channel_managers`) vão decidir o acesso a cada conversa (fase 2).
"""

import mimetypes
import secrets
import shutil
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

import structlog
from fastapi import HTTPException, Request
from sqlalchemy import Select, select, true, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from starlette.concurrency import run_in_threadpool

from chamados.core.permissions import Actor
from chamados.modules.audit.service import record
from chamados.modules.identity.deps import Auth
from chamados.modules.identity.models import User
from chamados.modules.jobs import service as jobs
from chamados.modules.organization.models import Team, TeamMember
from chamados.modules.whatsapp.bridge import Bridge, BridgeError
from chamados.modules.whatsapp.models import (
    STATES,
    WhatsAppChannel,
    WhatsAppChannelManager,
    WhatsAppChat,
    WhatsAppMessage,
)

log = structlog.get_logger(__name__)

MAX_TEXT = 4096
PAGE = 60  # mensagens por vez na conversa aberta
CHATS = 300  # conversas na lista

NOT_FOUND = "Conversa não encontrada."
NO_ACCESS = "Você não tem acesso a este número do WhatsApp."
EMPTY = "Escreva a mensagem."
TOO_LONG = "A mensagem passou do limite de 4096 caracteres."
CHANNEL_NOT_FOUND = "Número do WhatsApp não encontrado."
NAME_REQUIRED = "Informe o nome do número."
TEAM_NOT_FOUND = "Grupo não encontrado."
MANAGER_NOT_MEMBER = "Os responsáveis precisam ser membros do grupo."
DISK_FULL = "Espaço em disco insuficiente para guardar o arquivo. Avise quem administra o servidor."
NO_FILE = "Arquivo não encontrado."

# Abaixo disto de espaço livre, nenhum arquivo entra (o mesmo limite da ponte, media.js): disco
# cheio derruba o PostgreSQL, e os chamados param junto.
MIN_FREE = 0.1
# A ordem dos ticks: um estado só avança (o "entregue" atrasado não apaga o "lida").
RANK = {"pending": 0, "sent": 1, "delivered": 2, "read": 3}


# Acesso -----------------------------------------------------------------------------------------


def _visible(actor: Actor) -> Select[WhatsAppChannel]:
    return select(WhatsAppChannel).where(WhatsAppChannel.team_id.in_(actor.teams))


async def visible_channels(db: AsyncSession, actor: Actor) -> Sequence[WhatsAppChannel]:
    return (await db.scalars(_visible(actor).order_by(WhatsAppChannel.name))).all()


async def get_chat(db: AsyncSession, actor: Actor, chat_id: uuid.UUID) -> WhatsAppChat:
    chat = await db.scalar(select(WhatsAppChat).where(WhatsAppChat.public_id == chat_id))
    if chat is None:
        raise HTTPException(404, NOT_FOUND)
    channel = await db.get(WhatsAppChannel, chat.channel_id)
    if channel is None or channel.team_id not in actor.teams:
        raise HTTPException(403, NO_ACCESS)
    return chat


# Leitura ----------------------------------------------------------------------------------------


@dataclass
class ChatRow:
    chat: WhatsAppChat
    last: WhatsAppMessage | None


async def list_chats(
    db: AsyncSession,
    channel: WhatsAppChannel,
    *,
    unread: bool | None = None,
) -> list[ChatRow]:
    """As conversas do número, da mais recente para trás, com a última mensagem (LATERAL: uma
    leitura do índice por conversa). `unread`: só as não lidas (True) ou só as lidas (False)."""
    last = (
        select(WhatsAppMessage.id)
        .where(WhatsAppMessage.chat_id == WhatsAppChat.id)
        .order_by(WhatsAppMessage.sent_at.desc(), WhatsAppMessage.id.desc())
        .limit(1)
        .lateral()
    )
    message = aliased(WhatsAppMessage)
    query = (
        select(WhatsAppChat, message)
        .select_from(WhatsAppChat)
        .outerjoin(last, true())
        .outerjoin(message, message.id == last.c.id)
        .where(WhatsAppChat.channel_id == channel.id, WhatsAppChat.last_message_at.is_not(None))
        .order_by(WhatsAppChat.last_message_at.desc().nulls_last(), WhatsAppChat.id.desc())
        .limit(CHATS)
    )
    if unread is not None:
        query = query.where(WhatsAppChat.unread > 0 if unread else WhatsAppChat.unread == 0)
    rows = await db.execute(query)
    return [ChatRow(chat, msg) for chat, msg in rows]


async def list_messages(
    db: AsyncSession, chat: WhatsAppChat, *, after: int | None = None
) -> list[WhatsAppMessage]:
    """As últimas mensagens, da mais antiga para a mais nova; com `after`, só as que chegaram
    depois desse id (a atualização da conversa aberta)."""
    query = select(WhatsAppMessage).where(WhatsAppMessage.chat_id == chat.id)
    if after is not None:
        query = query.where(WhatsAppMessage.id > after)
    rows = (
        await db.scalars(
            query.order_by(WhatsAppMessage.sent_at.desc(), WhatsAppMessage.id.desc()).limit(PAGE)
        )
    ).all()
    return list(reversed(rows))


async def mark_read(db: AsyncSession, chat: WhatsAppChat) -> None:
    if chat.unread:
        chat.unread = 0
        await db.commit()


# Envio ------------------------------------------------------------------------------------------


def new_wa_id() -> str:
    """Id da mensagem no formato do WhatsApp Web, gerado antes do envio: a cópia que a ponte
    devolve tem o mesmo id e não entra duas vezes."""
    return "3EB0" + secrets.token_hex(10).upper()


def signed(text: str, name: str) -> str:
    """O nome de quem respondeu em negrito na primeira linha (o cliente vê um número só)."""
    return f"*{name}:*\n{text}"


async def _deliver(db: AsyncSession, bridge: Bridge, message: WhatsAppMessage) -> None:
    """Manda à ponte; sem ela (ou com o número desconectado), a fila tenta de novo."""
    chat = await db.get(WhatsAppChat, message.chat_id)
    channel = await db.get(WhatsAppChannel, chat.channel_id) if chat else None
    if chat is None or channel is None:
        return
    text = message.body or ""
    if channel.sign_messages and message.author is not None:
        text = signed(text, message.author.display_name).rstrip()
    if message.media_path:
        await bridge.send_media(
            channel.public_id,
            chat.jid,
            path=message.media_path,
            kind=message.kind,
            mime=message.mime_type,
            file_name=message.file_name,
            # O áudio não leva legenda: vai sem a assinatura.
            caption=None if message.kind == "audio" else (text or None),
            wa_id=message.wa_id,
        )
    else:
        await bridge.send_text(channel.public_id, chat.jid, text, message.wa_id)
    if RANK.get(message.status, 0) < RANK["sent"]:
        message.status = "sent"


async def send_text(
    db: AsyncSession, bridge: Bridge, auth: Auth, chat: WhatsAppChat, text: str
) -> WhatsAppMessage:
    text = text.strip()
    if not text:
        raise HTTPException(422, EMPTY)
    if len(text) > MAX_TEXT:
        raise HTTPException(422, TOO_LONG)
    now = datetime.now(UTC)
    message = WhatsAppMessage(
        chat_id=chat.id,
        wa_id=new_wa_id(),
        from_me=True,
        author_id=auth.user.id,
        kind="text",
        body=text,
        status="pending",
        sent_at=now,
    )
    db.add(message)
    chat.last_message_at = now
    await db.commit()
    await db.refresh(message, ["author"])
    try:
        await _deliver(db, bridge, message)
    except BridgeError as e:
        log.warning("whatsapp_envio_para_a_fila", message_id=message.id, erro=str(e))
        jobs.enqueue(db, "whatsapp.send", message_id=message.id)
    await db.commit()
    return message


def kind_for(mime: str | None) -> str:
    """O tipo da mensagem pelo tipo do arquivo; o resto vai como documento."""
    family = (mime or "").split("/", 1)[0]
    return {"image": "image", "video": "video", "audio": "audio"}.get(family, "document")


def disk_ok(path: Path) -> bool:
    path.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(path)
    return usage.total > 0 and usage.free / usage.total >= MIN_FREE


@dataclass
class Upload:
    """Um arquivo escolhido na tela: o nome, o tipo que o navegador informou e o conteúdo."""

    name: str
    content_type: str | None
    file: BinaryIO


def _copy(source: BinaryIO, target: Path) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as out:
        shutil.copyfileobj(source, out, 1024 * 1024)
    return target.stat().st_size


async def send_files(
    db: AsyncSession,
    media: Path,
    auth: Auth,
    chat: WhatsAppChat,
    uploads: Sequence[Upload],
    caption: str,
) -> list[WhatsAppMessage]:
    """Guarda os arquivos na pasta media e os põe na fila de envio, um por mensagem (a legenda vai
    no primeiro). Sem limite de tamanho além do do WhatsApp: só a reserva de disco."""
    caption = caption.strip()
    if len(caption) > MAX_TEXT:
        raise HTTPException(422, TOO_LONG)
    if not disk_ok(media):
        raise HTTPException(507, DISK_FULL)
    now = datetime.now(UTC)
    messages = []
    for i, upload in enumerate(uploads):
        name = Path(upload.name or "arquivo").name[:200] or "arquivo"
        mime = upload.content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
        relative = Path("out") / str(chat.public_id) / f"{uuid.uuid4().hex}-{name}"
        size = await run_in_threadpool(_copy, upload.file, media / relative)
        message = WhatsAppMessage(
            chat_id=chat.id,
            wa_id=new_wa_id(),
            from_me=True,
            author_id=auth.user.id,
            kind=kind_for(mime),
            body=caption if i == 0 and caption else None,
            file_name=name,
            media_path=str(relative),
            mime_type=mime,
            file_size=size,
            status="pending",
            sent_at=now,
        )
        db.add(message)
        messages.append(message)
    chat.last_message_at = now
    await db.flush()
    # Subir um arquivo grande ao WhatsApp leva minutos: vai sempre pela fila do worker.
    for message in messages:
        jobs.enqueue(db, "whatsapp.send", message_id=message.id)
    await db.commit()
    return messages


# Os tipos que o navegador mostra na própria tela; o resto só baixa (um HTML ou SVG mandado pelo
# cliente nunca abre dentro do TicketFlow).
INLINE = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "video/mp4",
    "video/webm",
    "audio/ogg",
    "audio/mpeg",
    "audio/mp4",
    "audio/aac",
    "audio/webm",
    "audio/wav",
}


def inline_mime(mime: str | None) -> str | None:
    base = (mime or "").split(";", 1)[0].strip().lower()
    return base if base in INLINE else None


async def chat_media(
    db: AsyncSession, media: Path, chat: WhatsAppChat, message_id: int
) -> tuple[WhatsAppMessage, Path]:
    """O arquivo de uma mensagem desta conversa (a conversa já passou pelo acesso)."""
    message = await db.get(WhatsAppMessage, message_id)
    if message is None or message.chat_id != chat.id:
        raise HTTPException(404, NO_FILE)
    return message, media_file(media, message)


def media_file(media: Path, message: WhatsAppMessage) -> Path:
    """O arquivo de uma mensagem, só dentro da pasta media."""
    if not message.media_path:
        raise HTTPException(404, NO_FILE)
    root = media.resolve()
    path = (root / message.media_path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404, NO_FILE)
    return path


async def retry_send(db: AsyncSession, bridge: Bridge, message_id: int) -> None:
    """Tarefa da fila (whatsapp.send): a ponte estava fora quando a pessoa enviou."""
    message = await db.get(WhatsAppMessage, message_id)
    if message is None or message.status != "pending":
        return
    await _deliver(db, bridge, message)
    await db.commit()


# O que chega da ponte -------------------------------------------------------------------------


def _timestamp(value: Any) -> datetime:
    try:
        return datetime.fromtimestamp(int(value), UTC)
    except (TypeError, ValueError, OverflowError):
        return datetime.now(UTC)


async def _chat(
    db: AsyncSession, channel: WhatsAppChannel, jid: str, name: str | None
) -> WhatsAppChat:
    await db.execute(
        insert(WhatsAppChat)
        .values(channel_id=channel.id, jid=jid, is_group=jid.endswith("@g.us"), name=name)
        .on_conflict_do_nothing(index_elements=["channel_id", "jid"])
    )
    return (
        await db.scalars(
            select(WhatsAppChat).where(
                WhatsAppChat.channel_id == channel.id, WhatsAppChat.jid == jid
            )
        )
    ).one()


async def _ingest_message(
    db: AsyncSession, channel: WhatsAppChannel, event: dict[str, Any]
) -> None:
    jid = str(event["jid"])
    group = jid.endswith("@g.us")
    push_name = event.get("push_name")
    # O nome da conversa: o assunto do grupo ou, na individual, o nome que o contato usa.
    name = event.get("chat_name") if group else (None if event.get("from_me") else push_name)
    chat = await _chat(db, channel, jid, name)
    if name and (group or not chat.name):
        chat.name = name
    sent_at = _timestamp(event.get("ts"))
    inserted = await db.scalar(
        insert(WhatsAppMessage)
        .values(
            chat_id=chat.id,
            wa_id=str(event["id"]),
            from_me=bool(event.get("from_me")),
            sender_jid=event.get("sender"),
            sender_name=None if event.get("from_me") else push_name,
            kind=event.get("kind") or "other",
            body=event.get("text"),
            file_name=event.get("file_name"),
            mime_type=event.get("mime"),
            file_size=event.get("size"),
            status=(event.get("status") or "sent") if event.get("from_me") else "received",
            sent_at=sent_at,
        )
        .on_conflict_do_nothing(index_elements=["chat_id", "wa_id"])
        .returning(WhatsAppMessage.id)
    )
    if inserted is None:
        return  # já estava guardada (a cópia do que enviamos daqui, ou um evento repetido)
    if chat.last_message_at is None or sent_at > chat.last_message_at:
        chat.last_message_at = sent_at
    if not event.get("from_me") and not event.get("history"):
        chat.unread += 1


async def _message_of(
    db: AsyncSession, channel: WhatsAppChannel, event: dict[str, Any]
) -> WhatsAppMessage | None:
    """A mensagem pelo id do WhatsApp, no número. Sem a conversa: o aviso de entregue ou lida pode
    chegar pelo LID do contato, e a conversa estar guardada pelo número (ou o contrário)."""
    return await db.scalar(
        select(WhatsAppMessage)
        .join(WhatsAppChat, WhatsAppChat.id == WhatsAppMessage.chat_id)
        .where(
            WhatsAppChat.channel_id == channel.id,
            WhatsAppMessage.wa_id == str(event.get("id")),
        )
        .order_by(WhatsAppMessage.id.desc())
        .limit(1)
    )


async def _ingest_status(db: AsyncSession, channel: WhatsAppChannel, event: dict[str, Any]) -> None:
    """Os ticks: o estado só avança."""
    status = event.get("status")
    message = await _message_of(db, channel, event)
    if message is not None and status in RANK and RANK[status] > RANK.get(message.status, 0):
        message.status = status


async def _ingest_media(db: AsyncSession, channel: WhatsAppChannel, event: dict[str, Any]) -> None:
    """A ponte baixou o arquivo de uma mensagem que chegou."""
    message = await _message_of(db, channel, event)
    if message is not None and event.get("path"):
        message.media_path = str(event["path"])
        message.mime_type = event.get("mime") or message.mime_type
        message.file_size = event.get("size") or message.file_size


async def _ingest_names(db: AsyncSession, channel: WhatsAppChannel, names: Iterable[Any]) -> None:
    for item in names:
        if isinstance(item, dict) and item.get("jid") and item.get("name"):
            await db.execute(
                update(WhatsAppChat)
                .where(WhatsAppChat.channel_id == channel.id, WhatsAppChat.jid == item["jid"])
                .values(name=item["name"])
            )


async def ingest(db: AsyncSession, events: Iterable[dict[str, Any]]) -> None:
    """Grava um lote de eventos da ponte (numa transação: a ponte só apaga depois do commit)."""
    channels: dict[str, WhatsAppChannel | None] = {}
    for event in events:
        key = str(event.get("channel"))
        if key not in channels:
            try:
                public_id = uuid.UUID(key)
            except ValueError:
                channels[key] = None
            else:
                channels[key] = await db.scalar(
                    select(WhatsAppChannel).where(WhatsAppChannel.public_id == public_id)
                )
        channel = channels[key]
        if channel is None:
            continue  # número que não existe mais no TicketFlow
        kind = event.get("type")
        if kind == "message" and event.get("id") and event.get("jid"):
            await _ingest_message(db, channel, event)
        elif kind == "names":
            await _ingest_names(db, channel, event.get("names") or [])
        elif kind == "status":
            await _ingest_status(db, channel, event)
        elif kind == "media":
            await _ingest_media(db, channel, event)
        elif kind == "connection" and event.get("state") in STATES:
            channel.state = event["state"]
            if event.get("phone"):
                channel.phone = str(event["phone"])
    await db.commit()


# Administração dos números ----------------------------------------------------------------------


async def all_channels(db: AsyncSession) -> Sequence[WhatsAppChannel]:
    return (await db.scalars(select(WhatsAppChannel).order_by(WhatsAppChannel.name))).all()


async def channel_by_id(db: AsyncSession, public_id: uuid.UUID) -> WhatsAppChannel:
    channel = await db.scalar(select(WhatsAppChannel).where(WhatsAppChannel.public_id == public_id))
    if channel is None:
        raise HTTPException(404, CHANNEL_NOT_FOUND)
    return channel


async def team_members(db: AsyncSession, team_id: int) -> Sequence[User]:
    return (
        await db.scalars(
            select(User)
            .join(TeamMember, TeamMember.user_id == User.id)
            .where(
                TeamMember.team_id == team_id, User.is_active.is_(True), User.deleted_at.is_(None)
            )
            .order_by(User.display_name)
        )
    ).all()


def _snapshot(channel: WhatsAppChannel) -> dict[str, Any]:
    return {
        "name": channel.name,
        "team_id": channel.team_id,
        "sign_messages": channel.sign_messages,
        "managers": sorted(m.user_id for m in channel.managers),
    }


async def _check(
    db: AsyncSession, name: str, team_id: uuid.UUID | None, managers: Iterable[uuid.UUID]
) -> tuple[str, Team, list[int]]:
    name = name.strip()
    if not name:
        raise HTTPException(422, NAME_REQUIRED)
    team = await db.scalar(select(Team).where(Team.public_id == team_id)) if team_id else None
    if team is None:
        raise HTTPException(422, TEAM_NOT_FOUND)
    wanted = set(managers)
    members = {u.public_id: u.id for u in await team_members(db, team.id)}
    if not wanted <= members.keys():
        raise HTTPException(422, MANAGER_NOT_MEMBER)
    return name[:100], team, sorted(members[m] for m in wanted)


async def create_channel(
    db: AsyncSession,
    auth: Auth,
    request: Request | None,
    *,
    name: str,
    team_id: uuid.UUID | None,
) -> WhatsAppChannel:
    name, team, _ = await _check(db, name, team_id, [])
    channel = WhatsAppChannel(name=name, team_id=team.id, managers=[])
    db.add(channel)
    await db.flush()
    record(
        db,
        "whatsapp_channel.created",
        request=request,
        actor_user_id=auth.user.id,
        target_type="whatsapp_channel",
        target_id=channel.public_id,
        after=_snapshot(channel),
    )
    await db.commit()
    return channel


async def update_channel(
    db: AsyncSession,
    auth: Auth,
    request: Request | None,
    channel: WhatsAppChannel,
    *,
    name: str,
    team_id: uuid.UUID | None,
    managers: Iterable[uuid.UUID],
    sign_messages: bool,
) -> None:
    name, team, manager_ids = await _check(db, name, team_id, managers)
    before = _snapshot(channel)
    channel.name = name
    channel.team_id = team.id
    channel.sign_messages = sign_messages
    # Só a diferença: tirar e pôr de volta a mesma pessoa na mesma descarga violaria a chave.
    channel.managers = [m for m in channel.managers if m.user_id in manager_ids]
    current = {m.user_id for m in channel.managers}
    channel.managers.extend(
        WhatsAppChannelManager(user_id=i) for i in manager_ids if i not in current
    )
    await db.flush()
    record(
        db,
        "whatsapp_channel.updated",
        request=request,
        actor_user_id=auth.user.id,
        target_type="whatsapp_channel",
        target_id=channel.public_id,
        before=before,
        after=_snapshot(channel),
    )
    await db.commit()


async def connect(db: AsyncSession, bridge: Bridge, channel: WhatsAppChannel) -> None:
    """Liga o número na ponte: sem sessão salva, ela gera o QR code para ler no celular."""
    result = await bridge.start(channel.public_id)
    if result.get("state") in STATES:
        channel.state = result["state"]
        await db.commit()


async def disconnect(
    db: AsyncSession,
    bridge: Bridge,
    auth: Auth,
    request: Request | None,
    channel: WhatsAppChannel,
) -> None:
    """Tira o TicketFlow dos aparelhos conectados do número. As conversas guardadas ficam."""
    await bridge.logout(channel.public_id)
    channel.state = "logged_out"
    record(
        db,
        "whatsapp_channel.disconnected",
        request=request,
        actor_user_id=auth.user.id,
        target_type="whatsapp_channel",
        target_id=channel.public_id,
        before={"phone": channel.phone},
    )
    await db.commit()
