"""Configurações da instalação: idioma padrão e cores (docs/13: /admin/configuracoes) e, na tela
Empresa (/admin/empresa), os dados da empresa, o logotipo e o logotipo dos relatórios.

`GET /branding` é público: a tela de login também usa as cores, o logotipo e o idioma.
Alterar exige admin.settings, e toda mudança vai para a auditoria (docs/08 §8.8).
"""

import base64
import binascii
import hashlib
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from chamados.core.i18n import Locale
from chamados.core.permissions import P
from chamados.db.session import DB
from chamados.modules.audit.service import record
from chamados.modules.identity.deps import Auth, CurrentAuth, require
from chamados.modules.system.company import Company, CompanyIn, clean, get_company
from chamados.modules.system.models import SystemSetting
from chamados.modules.system.service import get_value, set_value
from chamados.modules.system.work_hours import (
    TZ,
    Schedule,
    WorkHours,
    WorkHoursIn,
    get_holidays,
    get_work_hours,
    save_vigency,
    set_holidays,
    snapshot,
)

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
    report_logo_url: str | None = Field(description="o logotipo dos PDFs de relatório")


class SettingsUpdate(BaseModel):
    default_locale: Locale | None = None
    colors: Colors | None = Field(default=None, description="nulo volta às cores padrão")


class LogoIn(BaseModel):
    data_url: str = Field(
        max_length=400_000, description="data:image/png;base64,... (PNG, JPEG ou WebP)"
    )


# A chave de cada logotipo nas configurações → o endereço da imagem e o nome na auditoria.
LOGOS = {"logo": "logo", "report_logo": "report-logo"}


def _logo_url(key: str, sha: str | None) -> str | None:
    # A versão no endereço deixa o navegador guardar a imagem sem consultar de novo.
    return f"/api/v1/branding/{LOGOS[key]}?v={sha[:12]}" if sha else None


async def load_branding(db: AsyncSession) -> Branding:
    # Toda tela lê a marca: uma consulta só. Dos logotipos vem só o hash, não a imagem.
    rows = await db.execute(
        select(
            SystemSetting.key,
            case(
                (SystemSetting.key.in_(LOGOS), SystemSetting.value["sha256"]),
                else_=SystemSetting.value,
            ),
        ).where(SystemSetting.key.in_(("locale", "colors", *LOGOS)))
    )
    values: dict[str, Any] = {key: value for key, value in rows}
    return Branding(
        default_locale=values.get("locale") or "pt-BR",
        colors=values.get("colors"),
        logo_url=_logo_url("logo", values.get("logo")),
        report_logo_url=_logo_url("report_logo", values.get("report_logo")),
    )


@router.get("/branding", response_model=Branding)
async def branding(db: DB) -> Branding:
    return await load_branding(db)


async def _image(db: AsyncSession, key: str) -> Response:
    logo = await get_value(db, key)
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


@router.get("/branding/logo", response_class=Response)
async def branding_logo(db: DB) -> Response:
    return await _image(db, "logo")


@router.get("/branding/report-logo", response_class=Response)
async def branding_report_logo(db: DB) -> Response:
    """O logotipo dos PDFs de relatório (e da prévia do relatório para o cliente)."""
    return await _image(db, "report_logo")


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
    return await load_branding(db)


async def _save_logo(
    key: str, data: LogoIn, auth: Auth, request: Request, db: AsyncSession
) -> Branding:
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
    await set_value(db, key, value, auth.user.id)
    record(
        db,
        f"settings.{key}_changed",
        request=request,
        actor_user_id=auth.user.id,
        target_type="settings",
        after={"content_type": content_type, "bytes": len(raw), "sha256": sha},
    )
    await db.commit()
    return await load_branding(db)


async def _remove_logo(key: str, auth: Auth, request: Request, db: AsyncSession) -> Branding:
    logo = await get_value(db, key)
    if not logo:
        raise HTTPException(404, "Nenhum logotipo cadastrado.")
    await set_value(db, key, None, auth.user.id)
    record(
        db,
        f"settings.{key}_removed",
        request=request,
        actor_user_id=auth.user.id,
        target_type="settings",
        before={"sha256": logo["sha256"]},
    )
    await db.commit()
    return await load_branding(db)


@router.put("/admin/settings/logo", response_model=Branding)
async def set_logo(data: LogoIn, auth: Admin, request: Request, db: DB) -> Branding:
    return await _save_logo("logo", data, auth, request, db)


@router.delete("/admin/settings/logo", response_model=Branding)
async def remove_logo(auth: Admin, request: Request, db: DB) -> Branding:
    return await _remove_logo("logo", auth, request, db)


@router.put("/admin/settings/report-logo", response_model=Branding)
async def set_report_logo(data: LogoIn, auth: Admin, request: Request, db: DB) -> Branding:
    """O logotipo dos PDFs de relatório, separado do logotipo do aplicativo."""
    return await _save_logo("report_logo", data, auth, request, db)


@router.delete("/admin/settings/report-logo", response_model=Branding)
async def remove_report_logo(auth: Admin, request: Request, db: DB) -> Branding:
    return await _remove_logo("report_logo", auth, request, db)


@router.get("/admin/settings/company", response_model=Company | None)
async def company(auth: Admin, db: DB) -> Company | None:
    """Os dados da empresa que usa o sistema; nulo enquanto não foram cadastrados."""
    return await get_company(db)


@router.put("/admin/settings/company", response_model=Company)
async def set_company(data: CompanyIn, auth: Admin, request: Request, db: DB) -> Company:
    """Substitui os dados inteiros (o formulário envia todos os campos). A auditoria guarda só
    quais campos mudaram."""
    values = clean(data)
    stored = await get_value(db, "company") or {}
    changed = sorted(f for f, value in values.items() if stored.get(f) != value)
    if changed:
        await set_value(db, "company", values, auth.user.id)
        record(
            db,
            "settings.company_changed",
            request=request,
            actor_user_id=auth.user.id,
            target_type="settings",
            after={"fields": changed},
        )
        await db.commit()
    return Company.model_validate(values)


@router.get("/work-hours", response_model=WorkHours)
async def work_hours(auth: CurrentAuth, db: DB) -> WorkHours:
    """O expediente da instalação de hoje: o relatório de horas extras mostra a regra usada."""
    return await get_work_hours(db)


@router.put("/admin/settings/work-hours", response_model=WorkHours)
async def set_work_hours(data: WorkHoursIn, auth: Admin, request: Request, db: DB) -> WorkHours:
    """Grava o horário da instalação a partir de `valid_from` (sem ele, hoje: os dias de antes
    continuam com o de antes) e os feriados, que valem sempre."""
    if data.end <= data.start:
        raise HTTPException(422, "O fim do expediente precisa ser depois do início.")
    if (data.break_start is None) != (data.break_end is None):
        raise HTTPException(422, "Informe o início e o fim do intervalo, ou nenhum dos dois.")
    if (
        data.break_start
        and data.break_end
        and not data.start < data.break_start < data.break_end < data.end
    ):
        raise HTTPException(422, "O intervalo precisa ficar dentro do expediente.")
    valid_from = data.valid_from or datetime.now(TZ).date()
    schedule = Schedule(
        tuple(sorted(set(data.weekdays))),
        data.start.replace(second=0, microsecond=0),
        data.end.replace(second=0, microsecond=0),
        data.break_start.replace(second=0, microsecond=0) if data.break_start else None,
        data.break_end.replace(second=0, microsecond=0) if data.break_end else None,
    )
    holidays = sorted(set(data.holidays))
    before_holidays = await get_holidays(db)
    changed = await save_vigency(db, valid_from, schedule)
    await set_holidays(db, holidays, auth.user.id)
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    if changed is not None:
        before["work_hours"] = {
            "valid_from": valid_from.isoformat(),
            **(snapshot(changed[0]) or {}),
        }
        after["work_hours"] = {"valid_from": valid_from.isoformat(), **(snapshot(changed[1]) or {})}
    if before_holidays != holidays:
        before["holidays"] = [d.isoformat() for d in before_holidays]
        after["holidays"] = [d.isoformat() for d in holidays]
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
    return WorkHours(
        weekdays=list(schedule.weekdays),
        start=schedule.start,
        end=schedule.end,
        break_start=schedule.break_start,
        break_end=schedule.break_end,
        holidays=holidays,
    )
