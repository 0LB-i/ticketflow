"""Os dados da empresa que usa o sistema (Administração › Empresa): razão social e CNPJ, os
obrigatórios, e o resto opcional (inscrições, contato, endereço). Ficam na configuração
`company`, normalizados como os dos clientes (só dígitos no CNPJ, telefone e CEP), e vão para o
cabeçalho dos PDFs de relatório (`letterhead`).
"""

from typing import Annotated, Any

from fastapi import HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from chamados.core.text import optional_text, required_text
from chamados.modules.clients import documents as doc
from chamados.modules.system.service import get_value

Text200 = Annotated[str, Field(max_length=200)]
Short = Annotated[str, Field(max_length=50)]


class CompanyIn(BaseModel):
    name: Text200 = Field(description="razão social")
    trade_name: Text200 | None = Field(default=None, description="nome fantasia")
    document: Short = Field(description="CNPJ, com ou sem pontuação (o alfanumérico também)")
    state_registration: Short | None = Field(default=None, description='IE, ou "ISENTO"')
    municipal_registration: Short | None = Field(default=None, description="IM")
    phone: Short | None = Field(default=None, description="com o DDD")
    email: EmailStr | None = None
    website: Text200 | None = None
    postal_code: Short | None = None
    street: Text200 | None = None
    number: Short | None = Field(default=None, description='"S/N" quando não houver')
    complement: Text200 | None = None
    district: Text200 | None = None
    city: Text200 | None = None
    state: str | None = Field(default=None, min_length=2, max_length=2, description="UF")


class Company(CompanyIn):
    email: str | None = None  # na saída, o que está gravado (sem revalidar)


def clean(data: CompanyIn) -> dict[str, Any]:
    """Valida e normaliza. Devolve os valores como vão para a configuração."""
    v: dict[str, Any] = {
        field: optional_text(value) if isinstance(value, str) else value
        for field, value in data.model_dump().items()
    }
    v["name"] = required_text(" ".join(data.name.split()), "Informe a razão social.")
    v["document"] = doc.normalize_document(data.document)
    if not v["document"]:
        raise HTTPException(422, "Informe o CNPJ.")
    if not doc.valid_cnpj(v["document"]):
        raise HTTPException(422, "CNPJ inválido.")
    if v["state_registration"]:
        v["state_registration"] = v["state_registration"].upper()
    if v["phone"]:
        v["phone"] = doc.normalize_phone(v["phone"])
        if not doc.valid_phone(v["phone"]):
            raise HTTPException(422, "Telefone inválido: informe o DDD e o número.")
    if v["email"]:
        v["email"] = v["email"].lower()
    if v["postal_code"]:
        v["postal_code"] = doc.only_digits(v["postal_code"])
        if len(v["postal_code"]) != 8:
            raise HTTPException(422, "CEP inválido: são 8 números.")
    if v["state"]:
        v["state"] = v["state"].upper()
        if v["state"] not in doc.UFS:
            raise HTTPException(422, "UF inválida.")
    return v


async def get_company(db: AsyncSession) -> Company | None:
    stored = await get_value(db, "company")
    return Company.model_validate(stored) if stored else None


def letterhead(company: Company | None) -> list[str]:
    """As linhas da empresa no cabeçalho dos PDFs: a razão social, os documentos, o endereço e o
    contato (as que tiverem algo). Sem os dados cadastrados, nenhuma."""
    if company is None:
        return []
    documents = [f"CNPJ {doc.format_document(company.document, 'company')}"]
    if company.state_registration:
        documents.append(f"IE {company.state_registration}")
    if company.municipal_registration:
        documents.append(f"IM {company.municipal_registration}")
    street = ", ".join(p for p in (company.street, company.number, company.complement) if p)
    place = "/".join(p for p in (company.city, company.state) if p)
    postal = f"CEP {doc.format_postal_code(company.postal_code)}" if company.postal_code else ""
    address = [p for p in (street, company.district, place, postal) if p]
    phone = doc.format_phone(company.phone) if company.phone else ""
    contact = [p for p in (phone, company.email, company.website) if p]
    lines = [company.name, " · ".join(documents), " · ".join(address), " · ".join(contact)]
    return [line for line in lines if line]


async def get_letterhead(db: AsyncSession) -> list[str]:
    return letterhead(await get_company(db))
