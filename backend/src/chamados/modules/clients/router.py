"""Cadastro de clientes, pessoa física e jurídica (/clientes).

Ver exige client.view; cadastrar e alterar, client.manage. Não há exclusão: cliente que não é
mais atendido fica inativo. A auditoria guarda só quais campos mudaram, não os dados pessoais.
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from chamados.core.permissions import P
from chamados.db.session import DB
from chamados.modules.audit.service import record
from chamados.modules.clients import documents as doc
from chamados.modules.clients.models import Client
from chamados.modules.identity.deps import Auth, require

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
    name: Text200 = Field(description="nome completo ou razão social")
    trade_name: Text200 | None = Field(default=None, description="nome fantasia (PJ)")
    document: Short = Field(description="CPF ou CNPJ, com ou sem pontuação")
    id_number: Short | None = Field(default=None, description="RG (PF)")
    birth_date: date | None = Field(default=None, description="PF")
    state_registration: Short | None = Field(default=None, description='IE (PJ), ou "ISENTO"')
    municipal_registration: Short | None = Field(default=None, description="IM (PJ)")
    contact_name: Text200 | None = Field(default=None, description="pessoa de contato (PJ)")
    email: EmailStr
    phone: Short
    mobile: Short | None = None
    postal_code: Short
    street: Text200
    number: Short = Field(description='"S/N" quando não houver')
    complement: Text200 | None = None
    district: Text200
    city: Text200
    state: str = Field(min_length=2, max_length=2, description="UF")
    notes: str | None = Field(default=None, max_length=5000)
    is_active: bool = True


class ClientOut(ClientIn):
    id: uuid.UUID
    email: str  # na saída, o que está gravado (sem revalidar)
    created_at: datetime
    updated_at: datetime


class ClientSummary(BaseModel):
    id: uuid.UUID
    kind: ClientKind
    name: str
    trade_name: str | None
    document: str
    email: str
    phone: str
    city: str
    state: str
    is_active: bool


class ClientPage(BaseModel):
    items: list[ClientSummary]
    total: int


FIELDS = tuple(ClientIn.model_fields)


def _required(value: str | None, message: str) -> str:
    text = (value or "").strip()
    if not text:
        raise HTTPException(422, message)
    return text


def _optional(value: str | None) -> str | None:
    return (value or "").strip() or None


def _clean(data: ClientIn) -> dict[str, Any]:
    """Valida e normaliza. Devolve os valores como vão para o banco."""
    v: dict[str, Any] = {
        "kind": data.kind,
        "name": _required(data.name, "Informe o nome do cliente."),
        "trade_name": _optional(data.trade_name),
        "id_number": _optional(data.id_number),
        "birth_date": data.birth_date,
        "state_registration": _optional(data.state_registration),
        "municipal_registration": _optional(data.municipal_registration),
        "contact_name": _optional(data.contact_name),
        "email": str(data.email).strip().lower(),
        "street": _required(data.street, "Informe o endereço."),
        "number": _required(data.number, "Informe o número do endereço."),
        "complement": _optional(data.complement),
        "district": _required(data.district, "Informe o bairro."),
        "city": _required(data.city, "Informe a cidade."),
        "notes": _optional(data.notes),
        "is_active": data.is_active,
    }
    document = doc.normalize_document(data.document)
    if data.kind == "person" and not doc.valid_cpf(document):
        raise HTTPException(422, "CPF inválido.")
    if data.kind == "company" and not doc.valid_cnpj(document):
        raise HTTPException(422, "CNPJ inválido.")
    v["document"] = document
    if data.birth_date and data.birth_date > date.today():
        raise HTTPException(422, "A data de nascimento não pode ficar no futuro.")
    if v["state_registration"]:
        v["state_registration"] = v["state_registration"].upper()

    v["phone"] = doc.normalize_phone(data.phone)
    if not doc.valid_phone(v["phone"]):
        raise HTTPException(422, "Telefone inválido: informe o DDD e o número.")
    mobile = _optional(data.mobile)
    v["mobile"] = doc.normalize_phone(mobile) if mobile else None
    if v["mobile"] is not None and not doc.valid_phone(v["mobile"]):
        raise HTTPException(422, "Celular inválido: informe o DDD e o número.")

    v["postal_code"] = doc.only_digits(data.postal_code)
    if len(v["postal_code"]) != 8:
        raise HTTPException(422, "CEP inválido: são 8 números.")
    v["state"] = data.state.upper()
    if v["state"] not in doc.UFS:
        raise HTTPException(422, "UF inválida.")

    for field in COMPANY_ONLY if data.kind == "person" else PERSON_ONLY:
        v[field] = None
    return v


async def _check_document(db: AsyncSession, document: str, except_id: int | None) -> None:
    found = await db.scalar(select(Client.id).where(Client.document == document))
    if found is not None and found != except_id:
        raise HTTPException(409, "Já existe um cliente com este CPF/CNPJ.")


async def _client(db: AsyncSession, public_id: uuid.UUID) -> Client:
    client = await db.scalar(select(Client).where(Client.public_id == public_id))
    if client is None:
        raise HTTPException(404, "Cliente não encontrado.")
    return client


def _out(c: Client) -> ClientOut:
    return ClientOut.model_validate(
        {f: getattr(c, f) for f in FIELDS}
        | {"id": c.public_id, "created_at": c.created_at, "updated_at": c.updated_at}
    )


@router.get("", response_model=ClientPage)
async def list_clients(
    _: Viewer,
    db: DB,
    q: Annotated[str | None, Query(description="nome, nome fantasia, CPF/CNPJ ou e-mail")] = None,
    inactive: Annotated[bool, Query(description="incluir os inativos")] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ClientPage:
    stmt = select(Client)
    if not inactive:
        stmt = stmt.where(Client.is_active)
    if q and q.strip():
        term = f"%{q.strip()}%"
        filters: list[ColumnElement[bool]] = [
            func.unaccent(Client.name).ilike(func.unaccent(term)),
            func.unaccent(Client.trade_name).ilike(func.unaccent(term)),
            Client.email.ilike(term),
        ]
        document = doc.normalize_document(q)
        if len(document) >= 3:
            filters.append(Client.document.contains(document))
        stmt = stmt.where(or_(*filters))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = await db.scalars(
        stmt.order_by(func.lower(Client.name), Client.id).limit(limit).offset(offset)
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


@router.get("/{client_id}", response_model=ClientOut)
async def get_client(client_id: uuid.UUID, _: Viewer, db: DB) -> ClientOut:
    return _out(await _client(db, client_id))


@router.post("", response_model=ClientOut, status_code=201)
async def create_client(data: ClientIn, auth: Manager, request: Request, db: DB) -> ClientOut:
    values = _clean(data)
    await _check_document(db, values["document"], None)
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
    await _check_document(db, values["document"], client.id)
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
