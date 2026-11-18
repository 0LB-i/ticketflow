"""Números do WhatsApp (admin.organization): cadastrar o número, escolher o grupo que o usa e os
responsáveis, ligar pelo QR code e desconectar. O estado e o QR code vêm da ponte, ao vivo; sem
ela, a tela mostra o último estado guardado e avisa. As regras ficam em `modules/whatsapp/service`.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select

from chamados.core.i18n import translate
from chamados.core.permissions import P
from chamados.db.session import DB
from chamados.modules.organization.models import Team
from chamados.modules.whatsapp import service
from chamados.modules.whatsapp.bridge import BridgeError
from chamados.modules.whatsapp.models import WhatsAppChannel
from chamados.web.page import LoggedPage, check_csrf, requires
from chamados.web.whatsapp import BridgeDep

router = APIRouter()

Admin = Annotated[LoggedPage, requires(P.ADMIN_ORGANIZATION)]
Field = Annotated[str, Form()]
Checks = Annotated[list[str] | None, Form()]
URL = "/admin/whatsapp"


def _uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


async def _teams(db: DB) -> list[tuple[str, str]]:
    teams = await db.scalars(select(Team).where(Team.is_active.is_(True)).order_by(Team.name))
    return [(str(t.public_id), t.name) for t in teams]


async def _live(bridge: BridgeDep) -> tuple[dict[uuid.UUID, dict[str, Any]], bool]:
    """O estado de cada número na ponte; sem a ponte, um dicionário vazio e False."""
    try:
        return await bridge.channels(), True
    except BridgeError:
        return {}, False


def _state(channel: WhatsAppChannel, live: dict[uuid.UUID, dict[str, Any]], bridge_up: bool) -> str:
    """O estado na ponte. Sem a ponte, o último guardado; com ela, um número que não está rodando
    nela (pareamento abandonado, ponte reiniciada) volta a "não conectado"."""
    state = live.get(channel.public_id, {}).get("state")
    if state:
        return str(state)
    if bridge_up and channel.state != "logged_out":
        return "new"
    return channel.state


async def _list(
    page: LoggedPage,
    db: DB,
    bridge: BridgeDep,
    *,
    form: dict[str, str] | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    live, bridge_up = await _live(bridge)
    channels = await service.all_channels(db)
    return page.render(
        "admin/whatsapp.html",
        status_code=status_code,
        channels=[(c, _state(c, live, bridge_up)) for c in channels],
        bridge_up=bridge_up,
        teams=await _teams(db),
        form=form or {"nome": "", "grupo": ""},
        error=error,
    )


@router.get(URL)
async def channels_page(page: Admin, db: DB, bridge: BridgeDep) -> HTMLResponse:
    return await _list(page, db, bridge)


@router.post(URL)
async def create_channel(
    page: Admin,
    db: DB,
    bridge: BridgeDep,
    csrf_token: Field = "",
    nome: Field = "",
    grupo: Field = "",
) -> Response:
    check_csrf(page, csrf_token)
    try:
        channel = await service.create_channel(
            db, page.auth, page.request, name=nome, team_id=_uuid(grupo)
        )
    except HTTPException as exc:
        form = {"nome": nome, "grupo": grupo}
        return await _list(
            page, db, bridge, form=form, error=page.api_message(exc), status_code=422
        )
    response = RedirectResponse(f"{URL}/{channel.public_id}", status_code=303)
    page.flash(response, ("success", page.t("whatsappAdmin.criado")))
    return response


async def _edit(
    page: LoggedPage,
    db: DB,
    bridge: BridgeDep,
    channel_id: str,
    *,
    form: dict[str, Any] | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    public_id = _uuid(channel_id)
    if public_id is None:
        raise HTTPException(404)
    channel = await service.channel_by_id(db, public_id)
    live, bridge_up = await _live(bridge)
    members = await service.team_members(db, channel.team_id)
    managers = {m.user_id for m in channel.managers}
    return page.render(
        "admin/whatsapp_edit.html",
        status_code=status_code,
        channel=channel,
        state=_state(channel, live, bridge_up),
        qr_svg=live.get(channel.public_id, {}).get("qr_svg"),
        bridge_up=bridge_up,
        teams=await _teams(db),
        members=members,
        form=form
        or {
            "nome": channel.name,
            "grupo": str(channel.team.public_id),
            "responsaveis": [str(u.public_id) for u in members if u.id in managers],
            "assinar": channel.sign_messages,
        },
        error=error,
    )


@router.get(URL + "/{channel_id}")
async def edit_page(channel_id: str, page: Admin, db: DB, bridge: BridgeDep) -> HTMLResponse:
    return await _edit(page, db, bridge, channel_id)


@router.post(URL + "/{channel_id}")
async def save_channel(
    channel_id: str,
    page: Admin,
    db: DB,
    bridge: BridgeDep,
    csrf_token: Field = "",
    nome: Field = "",
    grupo: Field = "",
    responsaveis: Checks = None,
    assinar: Field = "",
) -> Response:
    check_csrf(page, csrf_token)
    channel = await service.channel_by_id(db, _uuid(channel_id) or uuid.UUID(int=0))
    chosen = [u for u in (_uuid(r) for r in responsaveis or []) if u]
    try:
        await service.update_channel(
            db,
            page.auth,
            page.request,
            channel,
            name=nome,
            team_id=_uuid(grupo),
            managers=chosen,
            sign_messages=bool(assinar),
        )
    except HTTPException as exc:
        # A validação vem antes de qualquer mudança: não há o que desfazer.
        form = {
            "nome": nome,
            "grupo": grupo,
            "responsaveis": [str(c) for c in chosen],
            "assinar": bool(assinar),
        }
        return await _edit(
            page, db, bridge, channel_id, form=form, error=page.api_message(exc), status_code=422
        )
    response = RedirectResponse(f"{URL}/{channel.public_id}", status_code=303)
    page.flash(response, ("success", page.t("whatsappAdmin.salvo")))
    return response


@router.post(URL + "/{channel_id}/conectar")
async def connect(
    channel_id: str, page: Admin, db: DB, bridge: BridgeDep, csrf_token: Field = ""
) -> Response:
    check_csrf(page, csrf_token)
    channel = await service.channel_by_id(db, _uuid(channel_id) or uuid.UUID(int=0))
    response = RedirectResponse(f"{URL}/{channel.public_id}", status_code=303)
    try:
        await service.connect(db, bridge, channel)
    except BridgeError as exc:
        page.flash(response, ("error", translate(str(exc), page.locale)))
    return response


@router.post(URL + "/{channel_id}/desconectar")
async def disconnect(
    channel_id: str, page: Admin, db: DB, bridge: BridgeDep, csrf_token: Field = ""
) -> Response:
    check_csrf(page, csrf_token)
    channel = await service.channel_by_id(db, _uuid(channel_id) or uuid.UUID(int=0))
    response = RedirectResponse(f"{URL}/{channel.public_id}", status_code=303)
    try:
        await service.disconnect(db, bridge, page.auth, page.request, channel)
    except BridgeError as exc:
        page.flash(response, ("error", translate(str(exc), page.locale)))
    else:
        page.flash(response, ("success", page.t("whatsappAdmin.desconectado")))
    return response
