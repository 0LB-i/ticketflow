"""Empresa (Administração › Empresa): os dados da empresa que usa o sistema, que vão para o
cabeçalho dos PDFs de relatório, o logotipo do aplicativo e o dos relatórios. Exige
admin.settings (conferido aqui por `requires`: na API fica numa dependência que não roda na
chamada direta). Cada parte grava pela rota da API dela.
"""

import base64
import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from chamados.core.permissions import P
from chamados.db.session import DB
from chamados.modules.clients import documents as doc
from chamados.modules.system import router as system_api
from chamados.modules.system.company import Company, CompanyIn, get_company
from chamados.modules.system.router import LOGO_MAX_BYTES, LogoIn
from chamados.web.page import LoggedPage, check_csrf, requires
from chamados.web.settings import run

router = APIRouter()

SettingsAdmin = Annotated[LoggedPage, requires(P.ADMIN_SETTINGS)]
Field = Annotated[str, Form()]
EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
LOGO_TYPES = ("image/png", "image/jpeg", "image/webp")
HOME = "/admin/empresa"


@dataclass
class CompanyForm:
    """O formulário como foi digitado (CNPJ, telefone e CEP com máscara)."""

    name: str = ""
    trade_name: str = ""
    document: str = ""
    state_registration: str = ""
    municipal_registration: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""
    postal_code: str = ""
    street: str = ""
    number: str = ""
    complement: str = ""
    district: str = ""
    city: str = ""
    state: str = ""

    @classmethod
    def of(cls, c: Company | None) -> "CompanyForm":
        if c is None:
            return cls()
        return cls(
            **{k: v or "" for k, v in c.model_dump().items()}
            | {
                "document": doc.format_document(c.document, "company"),
                "phone": doc.format_phone(c.phone) if c.phone else "",
                "postal_code": doc.format_postal_code(c.postal_code),
            }
        )

    def errors(self) -> dict[str, str]:
        """Campo → chave do texto do erro (os mesmos dos clientes), todos de uma vez."""
        found: dict[str, str] = {}
        if not self.name.strip():
            found["name"] = "clientes.erros.obrigatorio"
        document = doc.normalize_document(self.document)
        if not document:
            found["document"] = "clientes.erros.obrigatorio"
        elif not doc.valid_cnpj(document):
            found["document"] = "clientes.erros.cnpj"
        if self.phone.strip() and not doc.valid_phone(doc.normalize_phone(self.phone)):
            found["phone"] = "clientes.erros.telefone"
        if self.email.strip() and not EMAIL.match(self.email.strip()):
            found["email"] = "clientes.erros.email"
        if self.postal_code.strip() and len(doc.only_digits(self.postal_code)) != 8:
            found["postal_code"] = "clientes.erros.cep"
        if self.state and self.state not in doc.UFS:
            found["state"] = "clientes.erros.uf"
        return found

    def payload(self) -> dict[str, Any]:
        """O corpo do CompanyIn: vazio vira nulo."""
        return {k: v.strip() or None for k, v in asdict(self).items()}


def _render(
    page: LoggedPage,
    form: CompanyForm,
    errors: dict[str, str] | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    return page.render(
        "admin/company.html",
        status_code=status_code,
        form=form,
        errors=errors or {},
        error=error,
        uf_options=[(uf, uf) for uf in sorted(doc.UFS)],
    )


@router.get("/admin/empresa")
async def company_page(page: SettingsAdmin, db: DB) -> HTMLResponse:
    return _render(page, CompanyForm.of(await get_company(db)))


@router.post("/admin/empresa")
async def save_company(
    page: SettingsAdmin,
    request: Request,
    db: DB,
    csrf_token: Field = "",
    name: Field = "",
    trade_name: Field = "",
    document: Field = "",
    state_registration: Field = "",
    municipal_registration: Field = "",
    phone: Field = "",
    email: Field = "",
    website: Field = "",
    postal_code: Field = "",
    street: Field = "",
    number: Field = "",
    complement: Field = "",
    district: Field = "",
    city: Field = "",
    state: Field = "",
) -> Response:
    """Erro devolve a página com o que foi digitado (422)."""
    check_csrf(page, csrf_token)
    form = CompanyForm(
        name,
        trade_name,
        document,
        state_registration,
        municipal_registration,
        phone,
        email,
        website,
        postal_code,
        street,
        number,
        complement,
        district,
        city,
        state,
    )
    if errors := form.errors():
        return _render(page, form, errors, status_code=422)
    try:
        await system_api.set_company(
            CompanyIn.model_validate(form.payload()), page.auth, request, db
        )
    except ValidationError as exc:
        long = {
            str(e["loc"][0]): "clientes.erros.longo"
            for e in exc.errors()
            if e["type"] == "string_too_long"
        }
        return _render(page, form, long, None if long else page.t("comum.erroInesperado"), 422)
    except HTTPException as exc:
        return _render(page, form, error=page.api_message(exc), status_code=422)
    response = RedirectResponse(HOME, status_code=303)
    page.flash(response, ("success", page.t("comum.salvo")))
    return response


# --- logotipos -------------------------------------------------------------------------------


async def _upload(
    page: LoggedPage,
    anchor: str,
    logo: UploadFile | None,
    save: Callable[[LogoIn], Awaitable[object]],
) -> Response:
    """PNG, JPEG ou WebP até 256 KB; a API confere de novo, pelos primeiros bytes."""
    response = RedirectResponse(f"{HOME}#{anchor}", status_code=303)
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
    return await run(
        page,
        f"{HOME}#{anchor}",
        lambda: save(LogoIn(data_url=data_url)),
        page.t("configuracoes.logotipoSalvo"),
    )


@router.post("/admin/empresa/logo")
async def save_logo(
    page: SettingsAdmin,
    request: Request,
    db: DB,
    csrf_token: Field = "",
    logo: Annotated[UploadFile | None, File()] = None,
) -> Response:
    check_csrf(page, csrf_token)
    return await _upload(
        page, "logotipo", logo, lambda data: system_api.set_logo(data, page.auth, request, db)
    )


@router.post("/admin/empresa/logo/remover")
async def remove_logo(
    page: SettingsAdmin, request: Request, db: DB, csrf_token: Field = ""
) -> Response:
    check_csrf(page, csrf_token)
    return await run(
        page,
        f"{HOME}#logotipo",
        lambda: system_api.remove_logo(page.auth, request, db),
        page.t("configuracoes.logotipoRemovido"),
    )


@router.post("/admin/empresa/logo-relatorios")
async def save_report_logo(
    page: SettingsAdmin,
    request: Request,
    db: DB,
    csrf_token: Field = "",
    logo: Annotated[UploadFile | None, File()] = None,
) -> Response:
    """O logotipo dos PDFs de relatório, separado do logotipo do aplicativo."""
    check_csrf(page, csrf_token)
    return await _upload(
        page,
        "logotipo-relatorios",
        logo,
        lambda data: system_api.set_report_logo(data, page.auth, request, db),
    )


@router.post("/admin/empresa/logo-relatorios/remover")
async def remove_report_logo(
    page: SettingsAdmin, request: Request, db: DB, csrf_token: Field = ""
) -> Response:
    check_csrf(page, csrf_token)
    return await run(
        page,
        f"{HOME}#logotipo-relatorios",
        lambda: system_api.remove_report_logo(page.auth, request, db),
        page.t("configuracoes.logotipoRemovido"),
    )
