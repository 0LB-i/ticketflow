"""Cadastro de clientes, pessoa física e jurídica (/clientes).

Ver exige client.view; cadastrar e alterar, client.manage (as duas só para membros do grupo
Administradores, ver core/permissions.py). Para escolher o cliente de um chamado, qualquer
pessoa logada usa GET /clients/options, que devolve só o id e o nome. Só o CEP, a cidade e a UF são
obrigatórios; telefones e e-mails são listas. Não há exclusão: cliente que não é
mais atendido fica inativo. A auditoria guarda só quais campos mudaram, não os dados pessoais.
"""

import re
import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from chamados.core.permissions import P
from chamados.core.text import optional_text, required_text
from chamados.db.session import DB
from chamados.modules.audit.service import record
from chamados.modules.clients import documents as doc
from chamados.modules.clients.models import Client
from chamados.modules.identity.deps import Auth, CurrentAuth, require

router = APIRouter(prefix="/clients", tags=["clientes"])
Viewer = Annotated[Auth, Depends(require(P.CLIENT_VIEW))]
Manager = Annotated[Auth, Depends(require(P.CLIENT_MANAGE))]
ClientKind = Literal["person", "company"]

Text200 = Annotated[str, Field(max_length=200)]
Short = Annotated[str, Field(max_length=50)]

# Campos que só fazem sentido para um dos tipos: no outro, ficam vazios.
PERSON_ONLY = ("id_number", "birth_date")
COMPANY_ONLY = ("trade_name", "state_registration", "municipal_registration", "contact_name")


class ClientIn(BaseModel):
    kind: ClientKind
    name: Text200 | None = Field(default=None, description="nome completo ou razão social")
    trade_name: Text200 | None = Field(default=None, description="nome fantasia (PJ)")
    document: Short | None = Field(default=None, description="CPF ou CNPJ, com ou sem pontuação")
    id_number: Short | None = Field(default=None, description="RG (PF), só números, até 14")
    birth_date: date | None = Field(default=None, description="PF")
    state_registration: Short | None = Field(default=None, description='IE (PJ), ou "ISENTO"')
    municipal_registration: Short | None = Field(default=None, description="IM (PJ)")
    contact_name: Text200 | None = Field(default=None, description="pessoa de contato (PJ)")
    emails: list[EmailStr] = Field(default=[], max_length=20)
    phones: list[Short] = Field(default=[], max_length=20, description="com o DDD")
    postal_code: Short
    street: Text200 | None = None
    number: Short | None = Field(default=None, description='"S/N" quando não houver')
    complement: Text200 | None = None
    district: Text200 | None = None
    city: Text200
    state: str = Field(min_length=2, max_length=2, description="UF")
    notes: str | None = Field(default=None, max_length=5000)
    is_active: bool = True


class ClientOut(ClientIn):
    id: uuid.UUID
    label: str = Field(description="nome, nome fantasia ou cidade/UF, para exibir")
    emails: list[str]  # na saída, o que está gravado (sem revalidar)
    created_at: datetime
    updated_at: datetime


class ClientSummary(BaseModel):
    id: uuid.UUID
    kind: ClientKind
    label: str
    name: str | None
    trade_name: str | None
    document: str | None
    emails: list[str]
    phones: list[str]
    city: str
    state: str
    is_active: bool


class ClientPage(BaseModel):
    items: list[ClientSummary]
    total: int


class ClientOption(BaseModel):
    id: uuid.UUID
    label: str


class ClientOptions(BaseModel):
    items: list[ClientOption]


FIELDS = tuple(ClientIn.model_fields)


def _clean(data: ClientIn) -> dict[str, Any]:
    """Valida e normaliza. Devolve os valores como vão para o banco."""
    v: dict[str, Any] = {
        "kind": data.kind,
        "name": optional_text(" ".join((data.name or "").split())),  # sem espaços repetidos
        "trade_name": optional_text(data.trade_name),
        "id_number": optional_text(data.id_number),
        "birth_date": data.birth_date,
        "state_registration": optional_text(data.state_registration),
        "municipal_registration": optional_text(data.municipal_registration),
        "contact_name": optional_text(data.contact_name),
        "emails": list(dict.fromkeys(str(e).strip().lower() for e in data.emails)),
        "street": optional_text(data.street),
        "number": optional_text(data.number),
        "complement": optional_text(data.complement),
        "district": optional_text(data.district),
        "city": required_text(data.city, "Informe a cidade."),
        "notes": optional_text(data.notes),
        "is_active": data.is_active,
    }
    # PF: nome completo e CPF; PJ: razão social, nome fantasia e CNPJ.
    if data.kind == "person":
        required_text(data.name, "Informe o nome completo.")
    else:
        required_text(data.name, "Informe a razão social.")
        required_text(data.trade_name, "Informe o nome fantasia.")
    document = doc.normalize_document(data.document or "") or None
    if document is None and data.kind == "person":
        raise HTTPException(422, "Informe o CPF.")
    if document is None:
        raise HTTPException(422, "Informe o CNPJ.")
    if data.kind == "person" and not doc.valid_cpf(document):
        raise HTTPException(422, "CPF inválido.")
    if data.kind == "company" and not doc.valid_cnpj(document):
        raise HTTPException(422, "CNPJ inválido.")
    v["document"] = document
    if v["id_number"] and not re.fullmatch(r"[0-9]{1,14}", v["id_number"]):
        raise HTTPException(422, "RG inválido: só números, até 14.")
    if data.birth_date and data.birth_date > date.today():
        raise HTTPException(422, "A data de nascimento não pode ficar no futuro.")
    if v["state_registration"]:
        v["state_registration"] = v["state_registration"].upper()

    v["phones"] = list(dict.fromkeys(doc.normalize_phone(p) for p in data.phones))
    if not all(doc.valid_phone(p) for p in v["phones"]):
        raise HTTPException(422, "Telefone inválido: informe o DDD e o número.")

    v["postal_code"] = doc.only_digits(data.postal_code)
    if len(v["postal_code"]) != 8:
        raise HTTPException(422, "CEP inválido: são 8 números.")
    v["state"] = data.state.upper()
    if v["state"] not in doc.UFS:
        raise HTTPException(422, "UF inválida.")

    for field in COMPANY_ONLY if data.kind == "person" else PERSON_ONLY:
        v[field] = None
    return v


async def _check_unique(db: AsyncSession, values: dict[str, Any], except_id: int | None) -> None:
    """CPF/CNPJ e nome não repetem (o nome sem diferença de maiúsculas, acentos e espaços)."""
    others = select(Client.id).where(Client.id != (except_id or 0))
    if values["document"] and await db.scalar(others.where(Client.document == values["document"])):
        raise HTTPException(409, "Já existe um cliente com este CPF/CNPJ.")
    if values["name"] and await db.scalar(
        others.where(
            func.lower(func.unaccent(Client.name)) == func.lower(func.unaccent(values["name"]))
        )
    ):
        raise HTTPException(409, "Já existe um cliente com este nome.")


async def _client(db: AsyncSession, public_id: uuid.UUID) -> Client:
    client = await db.scalar(select(Client).where(Client.public_id == public_id))
    if client is None:
        raise HTTPException(404, "Cliente não encontrado.")
    return client


def _out(c: Client) -> ClientOut:
    return ClientOut.model_validate(
        {f: getattr(c, f) for f in FIELDS}
        | {
            "id": c.public_id,
            "label": c.label,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
        }
    )


@router.get("", response_model=ClientPage)
async def list_clients(
    _: Viewer,
    db: DB,
    q: Annotated[str | None, Query(description="nome, nome fantasia, CPF/CNPJ ou e-mail")] = None,
    inactive: Annotated[bool, Query(description="incluir os inativos")] = False,
    kind: Annotated[Literal["person", "company"] | None, Query(description="PF ou PJ")] = None,
    state: Annotated[str | None, Query(min_length=2, max_length=2, description="UF")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ClientPage:
    stmt = select(Client)
    if not inactive:
        stmt = stmt.where(Client.is_active)
    if kind:
        stmt = stmt.where(Client.kind == kind)
    if state:
        stmt = stmt.where(Client.state == state.upper())
    if q and q.strip():
        term = f"%{q.strip()}%"
        filters: list[ColumnElement[bool]] = [
            func.unaccent(Client.name).ilike(func.unaccent(term)),
            func.unaccent(Client.trade_name).ilike(func.unaccent(term)),
            func.array_to_string(Client.emails, " ").ilike(term),
        ]
        document = doc.normalize_document(q)
        if len(document) >= 3:
            filters.append(Client.document.contains(document))
        stmt = stmt.where(or_(*filters))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = await db.scalars(
        stmt.order_by(
            func.lower(func.coalesce(Client.name, Client.trade_name, Client.city)), Client.id
        )
        .limit(limit)
        .offset(offset)
    )
    return ClientPage(
        items=[
            ClientSummary.model_validate(
                {f: getattr(c, f) for f in ClientSummary.model_fields if f != "id"}
                | {"id": c.public_id}
            )
            for c in rows
        ],
        total=total,
    )


@router.get("/options", response_model=ClientOptions)
async def client_options(
    _: CurrentAuth,
    db: DB,
    q: Annotated[str | None, Query(max_length=200, description="nome ou nome fantasia")] = None,
) -> ClientOptions:
    """Clientes ativos para escolher no chamado e nos relatórios: só o id e o nome."""
    stmt = select(Client).where(Client.is_active)
    if q and q.strip():
        term = func.unaccent(f"%{q.strip()}%")
        stmt = stmt.where(
            or_(
                func.unaccent(Client.name).ilike(term), func.unaccent(Client.trade_name).ilike(term)
            )
        )
    rows = await db.scalars(
        stmt.order_by(
            func.lower(func.coalesce(Client.name, Client.trade_name, Client.city)), Client.id
        ).limit(50)
    )
    return ClientOptions(items=[ClientOption(id=c.public_id, label=c.label) for c in rows])


@router.get("/{client_id}", response_model=ClientOut)
async def get_client(client_id: uuid.UUID, _: Viewer, db: DB) -> ClientOut:
    return _out(await _client(db, client_id))


@router.post("", response_model=ClientOut, status_code=201)
async def create_client(data: ClientIn, auth: Manager, request: Request, db: DB) -> ClientOut:
    values = _clean(data)
    await _check_unique(db, values, None)
    client = Client(**values)
    db.add(client)
    await db.flush()
    record(
        db,
        "client.created",
        request=request,
        actor_user_id=auth.user.id,
        target_type="client",
        target_id=client.public_id,
    )
    await db.commit()
    return _out(await _client(db, client.public_id))


@router.put("/{client_id}", response_model=ClientOut)
async def update_client(
    client_id: uuid.UUID, data: ClientIn, auth: Manager, request: Request, db: DB
) -> ClientOut:
    """Substitui o cadastro inteiro (o formulário envia todos os campos)."""
    client = await _client(db, client_id)
    values = _clean(data)
    await _check_unique(db, values, client.id)
    changed = sorted(f for f, value in values.items() if getattr(client, f) != value)
    if changed:
        for field in changed:
            setattr(client, field, values[field])
        record(
            db,
            "client.updated",
            request=request,
            actor_user_id=auth.user.id,
            target_type="client",
            target_id=client.public_id,
            after={"fields": changed},
        )
        await db.commit()
        db.expire_all()
    return _out(await _client(db, client_id))
