"""Configurações da instalação (docs/13: /admin/configuracoes): idioma, cores, logotipo, status
dos chamados e expediente. Exige admin.settings (conferido aqui por `requires`: na API fica numa
dependência que não roda na chamada direta). Cada seção grava pela rota da API dela.
"""

import base64
import re
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from chamados.core.i18n import LOCALES
from chamados.core.permissions import P
from chamados.db.session import DB
from chamados.modules.catalog import router as catalog_api
from chamados.modules.catalog.router import StatusCreate, StatusOrder, StatusOut, StatusUpdate
from chamados.modules.system import router as system_api
from chamados.modules.system.router import LOGO_MAX_BYTES, LogoIn, SettingsUpdate
from chamados.modules.system.work_hours import WorkHours, get_work_hours
from chamados.web.page import LoggedPage, check_csrf, requires
from chamados.web.palette import DEFAULT_COLORS, PRESETS, TOKENS, Colors, palette

router = APIRouter()

SettingsAdmin = Annotated[LoggedPage, requires(P.ADMIN_SETTINGS)]
Field = Annotated[str, Form()]
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
COLOR_FIELDS = ("brand", "neutral", "background")
KINDS = ("open", "waiting", "delivered", "closed", "canceled")
DAYS = ("seg", "ter", "qua", "qui", "sex", "sab", "dom")
LOGO_TYPES = ("image/png", "image/jpeg", "image/webp")
HOME = "/admin/configuracoes"


def _variables(tokens: dict[str, str]) -> str:
    """Variáveis CSS (--tf-*) de um modo, para o atributo style da prévia."""
    return ";".join(f"--tf-{t}:{tokens[t]}" for t in TOKENS)


def format_date(locale: str, value: date) -> str:
    """Data curta como o Intl do navegador: "25/12/2026" ou "12/25/2026"."""
    if locale == "en":
        return f"{value.month}/{value.day}/{value.year}"
    return value.strftime("%d/%m/%Y")


def _removal_notice(page: LoggedPage, status: StatusOut, statuses: list[StatusOut]) -> str:
    """Para onde vão os chamados: o padrão do comportamento, ou o próximo, se o removido é o
    padrão."""
    others = [s for s in statuses if s.kind == status.kind and s.id != status.id]
    target = next((s for s in others if s.is_default), others[0] if others else None)
    n = status.ticket_count
    if n == 0:
        return page.t("statusConfig.removerSemChamados")
    name = target.name if target else ""
    if n == 1:
        return page.t("statusConfig.removerComUm", destino=name)
    return page.t("statusConfig.removerComVarios", n=n, destino=name)


def _count(page: LoggedPage, n: int) -> str:
    if n == 0:
        return page.t("statusConfig.chamados0")
    return page.t("statusConfig.chamados1") if n == 1 else page.t("statusConfig.chamadosN", n=n)


@router.get("/admin/configuracoes")
async def settings_page(
    page: SettingsAdmin,
    db: DB,
    brand: str = "",
    neutral: str = "",
    background: str = "",
    renomear: int | None = None,
) -> HTMLResponse:
    """brand/neutral/background: a prévia das cores digitadas (o HTMX troca só a prévia)."""
    branding = page.branding
    saved: Colors = branding.colors.model_dump() if branding.colors else dict(DEFAULT_COLORS)
    typed = {"brand": brand, "neutral": neutral, "background": background}
    colors = typed if all(HEX.match(v) for v in typed.values()) else saved
    colors = {k: v.upper() for k, v in colors.items()}
    preview = palette(colors)
    statuses = (await catalog_api.list_statuses(page.auth, db)).items
    hours = await get_work_hours(db)
    return page.render(
        "admin/settings.html",
        locale_options=[(loc, page.t(f"idioma.nomes.{loc}")) for loc in LOCALES],
        default_locale=branding.default_locale,
        colors=colors,
        color_fields=COLOR_FIELDS,
        presets=PRESETS,
        preview={mode: _variables(tokens) for mode, tokens in preview.items()},
        adjusted=preview["light"]["primary"]
        if preview["light"]["primary"].upper() != colors["brand"]
        else None,
        statuses=statuses,
        same_kind={s.id: sum(o.kind == s.kind for o in statuses) > 1 for s in statuses},
        counts={s.id: _count(page, s.ticket_count) for s in statuses},
        removal={s.id: _removal_notice(page, s, statuses) for s in statuses},
        renaming=renomear,
        kind_options=[(k, page.t(f"statusConfig.comportamentos.{k}")) for k in KINDS],
        days=DAYS,
        hours=hours,
        holidays=[(h.isoformat(), format_date(page.locale, h)) for h in hours.holidays],
    )


async def _run(
    page: LoggedPage,
    back: str,
    action: Callable[[], Awaitable[object]],
    done: str,
) -> RedirectResponse:
    response = RedirectResponse(back, status_code=303)
    try:
        await action()
    except ValidationError:
        page.flash(response, ("error", page.t("comum.erroInesperado")))
    except HTTPException as exc:
        page.flash(response, ("error", page.api_message(exc)))
    else:
        page.flash(response, ("success", done))
    return response


@router.post("/admin/configuracoes")
async def save_branding(
    page: SettingsAdmin,
    request: Request,
    db: DB,
    csrf_token: Field = "",
    default_locale: Field = "pt-BR",
    brand: Field = "",
    neutral: Field = "",
    background: Field = "",
) -> Response:
    """Idioma padrão e as três cores. As cores padrão gravam nulo (volta à paleta original)."""
    check_csrf(page, csrf_token)
    typed = {"brand": brand, "neutral": neutral, "background": background}
    if not all(HEX.match(v.strip()) for v in typed.values()):
        response = RedirectResponse(HOME, status_code=303)
        page.flash(response, ("error", page.t("configuracoes.hexInvalido")))
        return response
    upper = {k: v.strip().upper() for k, v in typed.items()}
    colors: dict[str, Any] | None = None if upper == DEFAULT_COLORS else upper
    return await _run(
        page,
        HOME,
        lambda: system_api.update_settings(
            SettingsUpdate.model_validate({"default_locale": default_locale, "colors": colors}),
            page.auth,
            request,
            db,
        ),
        page.t("comum.salvo"),
    )


@router.post("/admin/configuracoes/logo")
async def save_logo(
    page: SettingsAdmin,
    request: Request,
    db: DB,
    csrf_token: Field = "",
    logo: Annotated[UploadFile | None, File()] = None,
) -> Response:
    """PNG, JPEG ou WebP até 256 KB; a API confere de novo, pelos primeiros bytes."""
    check_csrf(page, csrf_token)
    response = RedirectResponse(f"{HOME}#logotipo", status_code=303)
    if logo is None or not logo.filename:
        return response
    if logo.content_type not in LOGO_TYPES:
        page.flash(response, ("error", page.t("configuracoes.logotipoTipo")))
        return response
    raw = await logo.read(LOGO_MAX_BYTES + 1)
    if len(raw) > LOGO_MAX_BYTES:
        page.flash(response, ("error", page.t("configuracoes.logotipoGrande")))
        return response
    data_url = f"data:{logo.content_type};base64,{base64.b64encode(raw).decode()}"
    return await _run(
        page,
        f"{HOME}#logotipo",
        lambda: system_api.set_logo(LogoIn(data_url=data_url), page.auth, request, db),
        page.t("configuracoes.logotipoSalvo"),
    )


@router.post("/admin/configuracoes/logo/remover")
async def remove_logo(
    page: SettingsAdmin, request: Request, db: DB, csrf_token: Field = ""
) -> Response:
    check_csrf(page, csrf_token)
    return await _run(
        page,
        f"{HOME}#logotipo",
        lambda: system_api.remove_logo(page.auth, request, db),
        page.t("configuracoes.logotipoRemovido"),
    )


# --- status dos chamados ---------------------------------------------------------------------


@router.post("/admin/configuracoes/status/novo")
async def create_status(
    page: SettingsAdmin,
    request: Request,
    db: DB,
    csrf_token: Field = "",
    name: Field = "",
    kind: Field = "open",
) -> Response:
    check_csrf(page, csrf_token)
    return await _run(
        page,
        f"{HOME}#status",
        lambda: catalog_api.create_status(
            StatusCreate.model_validate({"name": name, "kind": kind}), page.auth, request, db
        ),
        page.t("statusConfig.criado"),
    )


@router.post("/admin/configuracoes/status/{status_id}")
async def rename_status(
    status_id: int,
    page: SettingsAdmin,
    request: Request,
    db: DB,
    csrf_token: Field = "",
    name: Field = "",
) -> Response:
    """Só o nome muda: o comportamento não muda depois de criado."""
    check_csrf(page, csrf_token)
    statuses = (await catalog_api.list_statuses(page.auth, db)).items
    if any(st.id == status_id and st.name == name.strip() for st in statuses):
        return RedirectResponse(f"{HOME}#status", status_code=303)  # nome igual: nada a gravar
    return await _run(
        page,
        f"{HOME}#status",
        lambda: catalog_api.update_status(
            status_id, StatusUpdate.model_validate({"name": name}), page.auth, request, db
        ),
        page.t("comum.salvo"),
    )


@router.post("/admin/configuracoes/status/{status_id}/mover")
async def move_status(
    status_id: int,
    page: SettingsAdmin,
    db: DB,
    csrf_token: Field = "",
    para: Field = "cima",
) -> Response:
    """Sobe ou desce um lugar na ordem das listas."""
    check_csrf(page, csrf_token)

    async def action() -> None:
        ids = [s.id for s in await catalog_api.status_options(db)]
        if status_id not in ids:
            raise HTTPException(404, "Status não encontrado.")
        i = ids.index(status_id)
        j = i - 1 if para == "cima" else i + 1
        if 0 <= j < len(ids):
            ids[i], ids[j] = ids[j], ids[i]
        await catalog_api.reorder_statuses(StatusOrder(ids=ids), page.auth, db)

    return await _run(page, f"{HOME}#status", action, page.t("statusConfig.ordemSalva"))


@router.post("/admin/configuracoes/status/{status_id}/remover")
async def remove_status(
    status_id: int, page: SettingsAdmin, request: Request, db: DB, csrf_token: Field = ""
) -> Response:
    """Os chamados vão para o padrão do mesmo comportamento (a API decide e confere)."""
    check_csrf(page, csrf_token)
    statuses = (await catalog_api.list_statuses(page.auth, db)).items
    name = next((s.name for s in statuses if s.id == status_id), "")
    return await _run(
        page,
        f"{HOME}#status",
        lambda: catalog_api.delete_status(status_id, page.auth, request, db),
        page.t("statusConfig.removido", nome=name),
    )


# --- expediente ------------------------------------------------------------------------------


@router.post("/admin/configuracoes/expediente")
async def save_work_hours(
    page: SettingsAdmin,
    request: Request,
    db: DB,
    csrf_token: Field = "",
    weekdays: Annotated[list[int] | None, Form()] = None,
    start: Field = "",
    end: Field = "",
    holidays: Annotated[list[str] | None, Form()] = None,
) -> Response:
    """Dias, horário e feriados: o tempo de tarefa fora deles é hora extra nos relatórios."""
    check_csrf(page, csrf_token)
    back = f"{HOME}#expediente"
    if not start or not end or end <= start:
        response = RedirectResponse(back, status_code=303)
        page.flash(response, ("error", page.t("expediente.horarioInvalido")))
        return response
    return await _run(
        page,
        back,
        lambda: system_api.set_work_hours(
            WorkHours.model_validate(
                {
                    "weekdays": weekdays or [],
                    "start": start,
                    "end": end,
                    "holidays": [h for h in holidays or [] if h],
                }
            ),
            page.auth,
            request,
            db,
        ),
        page.t("comum.salvo"),
    )
