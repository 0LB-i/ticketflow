"""Chat do WhatsApp (/whatsapp): as conversas dos números dos grupos da pessoa, no jeito do WhatsApp
Web, e o envio de texto. A conversa aberta pergunta a cada 3 s se chegou mensagem (`depois`: 204
sem nada novo) e a lista, a cada 5 s; a fase 2 troca isso por SSE. As regras ficam em
`modules/whatsapp/service`.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from chamados.core.timezone import LOCAL_TZ
from chamados.db.session import DB
from chamados.modules.whatsapp import service
from chamados.modules.whatsapp.bridge import Bridge, get_bridge
from chamados.modules.whatsapp.models import WhatsAppChannel, WhatsAppChat, WhatsAppMessage
from chamados.web.formatting import format_date
from chamados.web.page import LoggedPage, LoggedPageDep, check_csrf

router = APIRouter()

Field = Annotated[str, Form()]
URL = "/whatsapp"


def bridge_dep(request: Request) -> Bridge:
    return get_bridge(request.app.state.settings)


BridgeDep = Annotated[Bridge, Depends(bridge_dep)]


def contact_label(jid: str) -> str:
    """O número do contato (+5511…), quando a conversa ainda não tem nome."""
    user = jid.split("@", 1)[0]
    return f"+{user}" if jid.endswith("@s.whatsapp.net") and user.isdigit() else user


def _uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


@dataclass
class Bubble:
    message: WhatsAppMessage
    day: str | None  # o separador do dia, na primeira mensagem de cada dia
    time: str
    # O nome em cima do balão: quem do TicketFlow respondeu, ou quem mandou no grupo.
    who: str | None


class Labels:
    """Hora e dia no fuso da máquina e no idioma da tela."""

    def __init__(self, page: LoggedPage) -> None:
        self.page = page
        self.today = datetime.now(UTC).astimezone(LOCAL_TZ).date()

    def time(self, value: datetime) -> str:
        t = value.astimezone(LOCAL_TZ)
        if self.page.locale == "en":
            return f"{t.hour % 12 or 12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"
        return t.strftime("%H:%M")

    def day(self, value: date) -> str:
        if value == self.today:
            return self.page.t("whatsapp.hoje")
        if value == self.today - timedelta(days=1):
            return self.page.t("whatsapp.ontem")
        return format_date(self.page.locale, value)

    def when(self, value: datetime | None) -> str:
        """Na lista: a hora, se foi hoje; senão o dia."""
        if value is None:
            return ""
        local = value.astimezone(LOCAL_TZ).date()
        return self.time(value) if local == self.today else self.day(local)


def _bubbles(page: LoggedPage, chat: WhatsAppChat, messages: list[WhatsAppMessage]) -> list[Bubble]:
    labels = Labels(page)
    bubbles = []
    previous: date | None = None
    for m in messages:
        local = m.sent_at.astimezone(LOCAL_TZ).date()
        who: str | None
        if m.from_me:
            who = m.author.display_name if m.author else page.t("whatsapp.peloCelular")
        elif chat.is_group:
            who = m.sender_name or (contact_label(m.sender_jid) if m.sender_jid else None)
        else:
            who = None
        bubbles.append(
            Bubble(m, labels.day(local) if local != previous else None, labels.time(m.sent_at), who)
        )
        previous = local
    return bubbles


async def _render(
    page: LoggedPage,
    db: DB,
    *,
    channel_id: uuid.UUID | None = None,
    chat: WhatsAppChat | None = None,
    only_list: bool = False,
    draft: str = "",
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    channels = list(await service.visible_channels(db, page.auth.actor))
    channel: WhatsAppChannel | None = None
    if chat is not None:
        channel = next((c for c in channels if c.id == chat.channel_id), None)
    elif channels:
        channel = next((c for c in channels if c.public_id == channel_id), channels[0])
    rows = await service.list_chats(db, channel) if channel else []
    messages: list[WhatsAppMessage] = []
    if chat is not None and not only_list:
        messages = await service.list_messages(db, chat)
        await service.mark_read(db, chat)
    labels = Labels(page)
    return page.render(
        "whatsapp/index.html",
        status_code=status_code,
        channels=channels,
        channel=channel,
        rows=rows,
        chat=chat,
        bubbles=_bubbles(page, chat, messages) if chat else [],
        last_id=messages[-1].id if messages else 0,
        when=labels.when,
        contact_label=contact_label,
        draft=draft,
        error=error,
    )


@router.get(URL)
async def whatsapp_page(page: LoggedPageDep, db: DB, numero: str | None = None) -> HTMLResponse:
    return await _render(page, db, channel_id=_uuid(numero))


@router.get(URL + "/conversa/{chat_id}")
async def chat_page(
    chat_id: str, page: LoggedPageDep, db: DB, depois: int | None = None
) -> Response:
    chat = await service.get_chat(db, page.auth.actor, _uuid(chat_id) or uuid.UUID(int=0))
    if depois is not None and not await service.list_messages(db, chat, after=depois):
        return Response(status_code=204)  # nada novo: o HTMX não troca nada
    return await _render(page, db, chat=chat)


@router.get(URL + "/conversa/{chat_id}/lista")
async def chat_list(chat_id: str, page: LoggedPageDep, db: DB) -> HTMLResponse:
    """A lista de conversas, com a conversa aberta marcada (a atualização a cada 5 s)."""
    chat = await service.get_chat(db, page.auth.actor, _uuid(chat_id) or uuid.UUID(int=0))
    return await _render(page, db, chat=chat, only_list=True)


@router.post(URL + "/conversa/{chat_id}/enviar")
async def send(
    chat_id: str,
    page: LoggedPageDep,
    db: DB,
    bridge: BridgeDep,
    csrf_token: Field = "",
    texto: Field = "",
) -> HTMLResponse:
    check_csrf(page, csrf_token)
    chat = await service.get_chat(db, page.auth.actor, _uuid(chat_id) or uuid.UUID(int=0))
    try:
        await service.send_text(db, bridge, page.auth, chat, texto)
    except HTTPException as exc:
        error = page.api_message(exc)
        return await _render(page, db, chat=chat, draft=texto, error=error, status_code=422)
    return await _render(page, db, chat=chat)
