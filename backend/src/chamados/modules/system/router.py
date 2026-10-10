"""Configurações da instalação: idioma padrão, cores e logotipo (docs/13: /admin/configuracoes).

`GET /branding` é público: a tela de login também usa as cores, o logotipo e o idioma.
Alterar exige admin.settings, e toda mudança vai para a auditoria (docs/08 §8.8).
"""

import base64
import binascii
import hashlib
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chamados.core.i18n import Locale
from chamados.core.permissions import P
from chamados.db.session import DB
from chamados.modules.audit.service import record
from chamados.modules.identity.deps import Auth, require
from chamados.modules.system.models import SystemSetting
from chamados.modules.system.service import get_value, set_value

router = APIRouter(tags=["configurações"])
Admin = Annotated[Auth, Depends(require(P.ADMIN_SETTINGS))]
HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]

LOGO_MAX_BYTES = 256 * 1024
INVALID_LOGO = "Logotipo inválido: envie uma imagem PNG, JPEG ou WebP."


def _is_image(content_type: str, raw: bytes) -> bool:
    """Confere o tipo pelos primeiros bytes. Só imagens rasterizadas: SVG pode ter scripts."""
    if content_type == "image/png":
        return raw.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/jpeg":
        return raw.startswith(b"\xff\xd8\xff")
    if content_type == "image/webp":
        return raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"
    return False


class Colors(BaseModel):
    """As 3 cores da identidade (docs/17 §17.2). A interface deriva delas a paleta inteira."""

    brand: HexColor = Field(description="cor da marca (laranja): ações e destaques")
    neutral: HexColor = Field(description="cor neutra (cinza): textos secundários e bordas")
    background: HexColor = Field(description="fundo das telas no modo claro (branco)")


class Branding(BaseModel):
    default_locale: Locale
    colors: Colors | None = Field(description="nulo: cores padrão do TicketFlow")
    logo_url: str | None


class SettingsUpdate(BaseModel):
    default_locale: Locale | None = None
    colors: Colors | None = Field(default=None, description="nulo volta às cores padrão")


class LogoIn(BaseModel):
    data_url: str = Field(
        max_length=400_000, description="data:image/png;base64,... (PNG, JPEG ou WebP)"
    )


async def _branding(db: AsyncSession) -> Branding:
    # Só o hash: a interface consulta o /branding toda vez que abre, e a imagem não é necessária.
    logo_sha = await db.scalar(
        select(SystemSetting.value["sha256"].astext).where(SystemSetting.key == "logo")
    )
    return Branding(
        default_locale=await get_value(db, "locale") or "pt-BR",
        colors=await get_value(db, "colors"),
        # A versão no endereço deixa o navegador guardar a imagem sem consultar de novo.
        logo_url=f"/api/v1/branding/logo?v={logo_sha[:12]}" if logo_sha else None,
    )


@router.get("/branding", response_model=Branding)
async def branding(db: DB) -> Branding:
    return await _branding(db)


@router.get("/branding/logo", response_class=Response)
async def branding_logo(db: DB) -> Response:
    logo = await get_value(db, "logo")
    if not logo:
        raise HTTPException(404, "Nenhum logotipo cadastrado.")
    return Response(
        base64.b64decode(logo["data"]),
        media_type=logo["content_type"],
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.patch("/admin/settings", response_model=Branding)
async def update_settings(data: SettingsUpdate, auth: Admin, request: Request, db: DB) -> Branding:
    changes = data.model_dump(exclude_unset=True)
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    if changes.get("default_locale"):
        before["locale"] = await get_value(db, "locale")
        after["locale"] = changes["default_locale"]
        await set_value(db, "locale", changes["default_locale"], auth.user.id)
    if "colors" in changes:
        colors = changes["colors"]
        if colors is not None:
            colors = {k: v.upper() for k, v in colors.items()}
        before["colors"] = await get_value(db, "colors")
        after["colors"] = colors
        await set_value(db, "colors", colors, auth.user.id)
    if before != after:
        record(
            db,
            "settings.updated",
            request=request,
            actor_user_id=auth.user.id,
            target_type="settings",
            before=before,
            after=after,
        )
    await db.commit()
    return await _branding(db)


@router.put("/admin/settings/logo", response_model=Branding)
async def set_logo(data: LogoIn, auth: Admin, request: Request, db: DB) -> Branding:
    header, _, encoded = data.data_url.partition(",")
    content_type = header.removeprefix("data:").removesuffix(";base64")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except binascii.Error:
        raw = b""
    if not header.endswith(";base64") or not _is_image(content_type, raw):
        raise HTTPException(422, INVALID_LOGO)
    if len(raw) > LOGO_MAX_BYTES:
        raise HTTPException(422, "O logotipo pode ter no máximo 256 KB.")
    sha = hashlib.sha256(raw).hexdigest()
    value = {"content_type": content_type, "data": base64.b64encode(raw).decode(), "sha256": sha}
    await set_value(db, "logo", value, auth.user.id)
    record(
        db,
        "settings.logo_changed",
        request=request,
        actor_user_id=auth.user.id,
        target_type="settings",
        after={"content_type": content_type, "bytes": len(raw), "sha256": sha},
    )
    await db.commit()
    return await _branding(db)


@router.delete("/admin/settings/logo", response_model=Branding)
async def remove_logo(auth: Admin, request: Request, db: DB) -> Branding:
    logo = await get_value(db, "logo")
    if not logo:
        raise HTTPException(404, "Nenhum logotipo cadastrado.")
    await set_value(db, "logo", None, auth.user.id)
    record(
        db,
        "settings.logo_removed",
        request=request,
        actor_user_id=auth.user.id,
        target_type="settings",
        before={"sha256": logo["sha256"]},
    )
    await db.commit()
    return await _branding(db)
