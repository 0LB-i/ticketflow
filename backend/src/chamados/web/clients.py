"""Cadastro de clientes, pessoa física e jurídica (Administração › Clientes).

Ver exige client.view; cadastrar e alterar, client.manage (só membros do grupo Administradores,
core/permissions.py). As regras e a gravação são as da API (`clients/router.py`); a tela confere
antes os mesmos campos que a SPA conferia, para mostrar todos os erros de uma vez.
"""

import re
import uuid
from dataclasses import dataclass, field, fields
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from chamados.core.permissions import P
from chamados.db.session import DB
from chamados.modules.clients import documents as doc
from chamados.modules.clients import router as clients_api
from chamados.modules.clients.router import ClientIn, ClientOut
from chamados.web.formatting import format_document, format_phone, format_postal_code
from chamados.web.page import LoggedPage, check_csrf, requires

router = APIRouter()

Viewer = Annotated[LoggedPage, requires(P.CLIENT_VIEW)]
Manager = Annotated[LoggedPage, requires(P.CLIENT_MANAGE)]
UFS = sorted(doc.UFS)
EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
WITH_HOURS = ("monthly", "annual")  # contratos com horas (por mês ou por ano)


@router.get("/admin/clientes")
async def clients_page(
    page: Viewer,
    db: DB,
    q: str = "",
    tipo: str = "",
    uf: str = "",
    inativos: bool = False,
) -> HTMLResponse:
    """Lista com a busca (nome, CPF/CNPJ, e-mail), o tipo, a UF e os inativos."""
    kind: Literal["person", "company"] | None = (
        "person" if tipo == "person" else "company" if tipo == "company" else None
    )
    state = uf if uf in doc.UFS else None
    result = await clients_api.list_clients(
        page.auth,
        db,
        q=q.strip() or None,
        inactive=inativos,
        kind=kind,
        state=state,
        limit=200,
        offset=0,
    )
    return page.render(
        "clients/list.html",
        clients=result.items,
        total=result.total,
        filters={"q": q, "tipo": kind or "", "uf": state or "", "inativos": inativos},
        uf_options=[(uf, uf) for uf in UFS],
        format_document=format_document,
        format_phone=format_phone,
    )


@dataclass
class ClientForm:
    """O formulário como foi digitado (documentos com máscara)."""

    kind: str = "person"
    name: str = ""
    trade_name: str = ""
    document: str = ""
    id_number: str = ""
    birth_date: str = ""
    state_registration: str = ""
    municipal_registration: str = ""
    contact_name: str = ""
    postal_code: str = ""
    street: str = ""
    number: str = ""
    complement: str = ""
    district: str = ""
    city: str = ""
    state: str = ""
    notes: str = ""
    contract_type: str = ""
    contract_hours: str = ""
    is_active: bool = True
    phones: list[str] = field(default_factory=lambda: [""])
    emails: list[str] = field(default_factory=lambda: [""])

    @classmethod
    def of(cls, c: ClientOut) -> "ClientForm":
        text = {
            f.name: str(getattr(c, f.name) or "")
            for f in fields(cls)
            if f.name not in ("is_active", "phones", "emails")
        }
        return cls(
            **text
            | {
                "document": format_document(c.document, c.kind),
                "postal_code": format_postal_code(c.postal_code),
            },
            is_active=c.is_active,
            phones=[format_phone(p) for p in c.phones] or [""],
            emails=list(c.emails) or [""],
        )

    def errors(self) -> dict[str, str]:
        """Chave do campo → chave do texto do erro (os mesmos da SPA)."""
        person = self.kind == "person"
        found: dict[str, str] = {}
        if not self.name.strip():
            found["name"] = "clientes.erros.obrigatorio"
        if not person and not self.trade_name.strip():
            found["trade_name"] = "clientes.erros.obrigatorio"
        document = doc.normalize_document(self.document)
        if not document:
            found["document"] = "clientes.erros.obrigatorio"
        elif not (doc.valid_cpf(document) if person else doc.valid_cnpj(document)):
            found["document"] = "clientes.erros.cpf" if person else "clientes.erros.cnpj"
        if len(doc.only_digits(self.postal_code)) != 8:
            found["postal_code"] = "clientes.erros.cep"
        if not self.city.strip():
            found["city"] = "clientes.erros.obrigatorio"
        if self.state not in doc.UFS:
            found["state"] = "clientes.erros.uf"
        for i, phone in enumerate(self.phones):
            if phone.strip() and not doc.valid_phone(doc.normalize_phone(phone)):
                found[f"phones.{i}"] = "clientes.erros.telefone"
        for i, email in enumerate(self.emails):
            if email.strip() and not EMAIL.match(email.strip()):
                found[f"emails.{i}"] = "clientes.erros.email"
        if self.contract_type in WITH_HOURS:
            hours = self.contract_hours.strip()
            if not hours:
                found["contract_hours"] = "clientes.erros.obrigatorio"
            elif not (hours.isdigit() and 1 <= int(hours) <= 10000):
                found["contract_hours"] = "clientes.erros.horas"
        return found

    def payload(self) -> dict[str, Any]:
        """O corpo do ClientIn: campos do outro tipo vazios, linhas vazias fora."""
        person = self.kind == "person"

        def optional(value: str, keep: bool = True) -> str | None:
            return (value.strip() or None) if keep else None

        return {
            "kind": self.kind,
            "name": optional(self.name),
            "trade_name": optional(self.trade_name, not person),
            "document": optional(self.document),
            "id_number": optional(self.id_number, person),
            "birth_date": optional(self.birth_date, person),
            "state_registration": optional(self.state_registration, not person),
            "municipal_registration": optional(self.municipal_registration, not person),
            "contact_name": optional(self.contact_name, not person),
            "emails": [e.strip() for e in self.emails if e.strip()],
            "phones": [p.strip() for p in self.phones if p.strip()],
            "postal_code": self.postal_code,
            "street": optional(self.street),
            "number": optional(self.number),
            "complement": optional(self.complement),
            "district": optional(self.district),
            "city": self.city.strip(),
            "state": self.state,
            "notes": optional(self.notes),
            "contract_type": self.contract_type or None,
            "contract_hours": optional(self.contract_hours, self.contract_type in WITH_HOURS),
            "is_active": self.is_active,
        }


def _field_errors(form: ClientForm, exc: ValidationError) -> dict[str, str]:
    """Erros da validação da API (e-mail, tamanhos) no campo da tela."""
    # Nas listas, o índice é o da lista sem as linhas vazias (payload): volta para a da tela.
    lines = {
        "emails": [i for i, v in enumerate(form.emails) if v.strip()],
        "phones": [i for i, v in enumerate(form.phones) if v.strip()],
    }
    found: dict[str, str] = {}
    for e in exc.errors():
        field, *rest = e["loc"]
        message = "clientes.erros.longo" if e["type"] == "string_too_long" else None
        if field in lines and rest and isinstance(rest[0], int):
            found[f"{field}.{lines[str(field)][rest[0]]}"] = message or (
                "clientes.erros.email" if field == "emails" else "clientes.erros.telefone"
            )
        elif isinstance(field, str) and message:
            found[field] = message
    return found


def _form_page(
    page: LoggedPage,
    form: ClientForm,
    client_id: uuid.UUID | None,
    title: str,
    errors: dict[str, str] | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    return page.render(
        "clients/form.html",
        status_code=status_code,
        form=form,
        client_id=client_id,
        title=title,
        can_edit=page.can("client.manage"),
        errors=errors or {},
        error=error,
        uf_options=[(uf, uf) for uf in UFS],
    )


@router.get("/admin/clientes/novo")
async def new_client_page(page: Manager) -> HTMLResponse:
    return _form_page(page, ClientForm(), None, page.t("clientes.novo"))


def _client_id(raw: str) -> uuid.UUID:
    """Id da URL: um endereço inválido é "não encontrado", como na SPA (não "dados inválidos")."""
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise HTTPException(404, "Cliente não encontrado.") from None


@router.get("/admin/clientes/{client_id}")
async def client_page(client_id: str, page: Viewer, db: DB) -> HTMLResponse:
    """Sem client.manage, o formulário só mostra os dados."""
    client = await clients_api.get_client(_client_id(client_id), page.auth, db)
    return _form_page(page, ClientForm.of(client), client.id, client.label)


Field = Annotated[str, Form()]
Lines = Annotated[list[str] | None, Form()]


async def _save(
    page: LoggedPage,
    request: Request,
    db: DB,
    client_id: uuid.UUID | None,
    values: dict[str, Any],
) -> Response:
    check_csrf(page, values.pop("csrf_token"))
    # Só a edição tem a caixa "Cliente ativo"; o cadastro começa ativo.
    checked = values.pop("is_active") == "1"
    active = checked if client_id else True
    phones = values.pop("phones") or [""]
    emails = values.pop("emails") or [""]
    values["state"] = values["state"].strip().upper()  # como a API, aceita "sp"
    form = ClientForm(**values, is_active=active, phones=phones, emails=emails)
    # Como na primeira abertura: o nome do cliente (na edição) ou "Novo cliente".
    title = (form.name or form.trade_name or page.t("clientes.editar")) if client_id else ""
    title = title or page.t("clientes.novo")
    if errors := form.errors():
        return _form_page(page, form, client_id, title, errors=errors, status_code=422)
    try:
        data = ClientIn.model_validate(form.payload())
        if client_id:
            await clients_api.update_client(client_id, data, page.auth, request, db)
        else:
            await clients_api.create_client(data, page.auth, request, db)
    except ValidationError as exc:
        # E-mail que passa no formato simples mas não na validação da API: marca o campo.
        if fields := _field_errors(form, exc):
            return _form_page(page, form, client_id, title, errors=fields, status_code=422)
        error = page.t("comum.erroInesperado")
    except HTTPException as exc:
        error = page.api_message(exc)
    else:
        response = RedirectResponse("/admin/clientes", status_code=303)
        done = page.t("comum.salvo") if client_id else page.t("clientes.cadastrado")
        page.flash(response, ("success", done))
        return response
    return _form_page(page, form, client_id, title, error=error, status_code=422)


def _fields(
    csrf_token: Field = "",
    kind: Field = "person",
    name: Field = "",
    trade_name: Field = "",
    document: Field = "",
    id_number: Field = "",
    birth_date: Field = "",
    state_registration: Field = "",
    municipal_registration: Field = "",
    contact_name: Field = "",
    postal_code: Field = "",
    street: Field = "",
    number: Field = "",
    complement: Field = "",
    district: Field = "",
    city: Field = "",
    state: Field = "",
    notes: Field = "",
    contract_type: Field = "",
    contract_hours: Field = "",
    is_active: Field = "",
    phones: Lines = None,
    emails: Lines = None,
) -> dict[str, Any]:
    """Os campos do formulário, como dependência (as duas rotas de gravação os recebem)."""
    return dict(locals())


Values = Annotated[dict[str, Any], Depends(_fields)]


@router.post("/admin/clientes/novo")
async def create_client(page: Manager, request: Request, db: DB, values: Values) -> Response:
    return await _save(page, request, db, None, values)


@router.post("/admin/clientes/{client_id}")
async def update_client(
    client_id: str, page: Manager, request: Request, db: DB, values: Values
) -> Response:
    return await _save(page, request, db, _client_id(client_id), values)
