"""Cadastro de clientes: pessoa física e jurídica, validações e permissões."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from chamados.modules.audit.models import AuditLog
from chamados.modules.clients.documents import valid_cnpj, valid_cpf
from tests.conftest import criar_usuario, entrar

API = "/api/v1/clients"

ENDERECO = {
    "postal_code": "01310-100",
    "street": "Avenida Paulista",
    "number": "1000",
    "complement": "Conjunto 12",
    "district": "Bela Vista",
    "city": "São Paulo",
    "state": "sp",
}
PESSOA = {
    "kind": "person",
    "name": "João da Silva",
    "document": "529.982.247-25",
    "id_number": "123456789",
    "birth_date": "1985-04-12",
    "email": "Joao@Exemplo.com",
    "phone": "(11) 3333-4444",
    "mobile": "+55 11 98765-4321",
    **ENDERECO,
}
EMPRESA = {
    "kind": "company",
    "name": "Padaria Pão Quente Ltda",
    "trade_name": "Pão Quente",
    "document": "12.ABC.345/01DE-35",  # CNPJ alfanumérico
    "state_registration": "isento",
    "municipal_registration": "1234567",
    "contact_name": "Maria",
    "email": "contato@paoquente.com.br",
    "phone": "1133334444",
    **ENDERECO,
}


@pytest.fixture
def agente(client: TestClient, db: Session) -> None:
    criar_usuario(db, "ana@x.com")
    entrar(client, "ana@x.com")


@pytest.mark.parametrize(
    ("cpf", "valido"), [("52998224725", True), ("52998224724", False), ("11111111111", False)]
)
def test_cpf(cpf: str, valido: bool) -> None:
    assert valid_cpf(cpf) is valido


@pytest.mark.parametrize(
    ("cnpj", "valido"),
    [("11222333000181", True), ("12ABC34501DE35", True), ("12ABC34501DE36", False)],
)
def test_cnpj_numerico_e_alfanumerico(cnpj: str, valido: bool) -> None:
    assert valid_cnpj(cnpj) is valido


def test_cadastra_pessoa_fisica_normalizado(client: TestClient, db: Session, agente: None) -> None:
    r = client.post(API, json={**PESSOA, "trade_name": "não se aplica"})
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["document"] == "52998224725"
    assert c["email"] == "joao@exemplo.com"
    assert c["phone"] == "1133334444" and c["mobile"] == "11987654321"
    assert c["postal_code"] == "01310100" and c["state"] == "SP"
    assert c["trade_name"] is None  # campo de PJ fica vazio na PF
    assert client.get(f"{API}/{c['id']}").json()["birth_date"] == "1985-04-12"

    # A auditoria não guarda os dados pessoais
    log = db.scalars(select(AuditLog).where(AuditLog.target_type == "client")).one()
    assert log.action == "client.created" and log.after is None


def test_cadastra_pessoa_juridica(client: TestClient, agente: None) -> None:
    c = client.post(API, json=EMPRESA).json()
    assert c["document"] == "12ABC34501DE35"
    assert c["state_registration"] == "ISENTO"
    assert c["id_number"] is None and c["birth_date"] is None


@pytest.mark.parametrize(
    ("mudanca", "mensagem"),
    [
        ({"document": "529.982.247-24"}, "CPF inválido."),
        ({"document": "529.982.247-251"}, "CPF inválido."),
        ({"document": "529.982.247-2A"}, "CPF inválido."),
        ({"document": "529.982.247-2"}, "CPF inválido."),
        ({"id_number": "12.345.678-9"}, "RG inválido: só números, até 14."),
        ({"id_number": "12345678X"}, "RG inválido: só números, até 14."),
        ({"id_number": "123456789012345"}, "RG inválido: só números, até 14."),
        ({"kind": "company"}, "CNPJ inválido."),
        ({"phone": "3333-4444"}, "Telefone inválido: informe o DDD e o número."),
        ({"mobile": "123"}, "Celular inválido: informe o DDD e o número."),
        ({"postal_code": "1310-100"}, "CEP inválido: são 8 números."),
        ({"state": "XX"}, "UF inválida."),
        ({"street": "  "}, "Informe o endereço."),
        ({"birth_date": "2999-01-01"}, "A data de nascimento não pode ficar no futuro."),
    ],
)
def test_validacoes(
    client: TestClient, agente: None, mudanca: dict[str, Any], mensagem: str
) -> None:
    r = client.post(API, json={**PESSOA, **mudanca})
    assert r.status_code == 422
    assert r.json()["detail"] == mensagem


def test_email_obrigatorio_e_valido(client: TestClient, agente: None) -> None:
    assert client.post(API, json={**PESSOA, "email": "joao"}).status_code == 422
    sem_email = {k: v for k, v in PESSOA.items() if k != "email"}
    assert client.post(API, json=sem_email).status_code == 422


def test_documento_unico_e_edicao(client: TestClient, db: Session, agente: None) -> None:
    c = client.post(API, json=PESSOA).json()
    r = client.post(API, json={**PESSOA, "document": "52998224725"})
    assert r.status_code == 409

    r = client.put(f"{API}/{c['id']}", json={**PESSOA, "city": "Campinas", "is_active": False})
    assert r.status_code == 200
    assert r.json()["city"] == "Campinas" and r.json()["is_active"] is False
    log = db.scalars(select(AuditLog).where(AuditLog.action == "client.updated")).one()
    assert log.after == {"fields": ["city", "is_active"]}

    # Sem mudança, sem auditoria
    client.put(f"{API}/{c['id']}", json={**PESSOA, "city": "Campinas", "is_active": False})
    assert len(db.scalars(select(AuditLog).where(AuditLog.action == "client.updated")).all()) == 1


def test_busca_e_inativos(client: TestClient, agente: None) -> None:
    pessoa = client.post(API, json=PESSOA).json()
    client.post(API, json=EMPRESA)
    assert client.get(API).json()["total"] == 2
    assert [c["name"] for c in client.get(API, params={"q": "joao"}).json()["items"]] == [
        "João da Silva"
    ]
    assert client.get(API, params={"q": "pão quente"}).json()["total"] == 1
    assert client.get(API, params={"q": "529.982"}).json()["total"] == 1
    assert client.get(API, params={"q": "12.abc"}).json()["total"] == 1

    client.put(f"{API}/{pessoa['id']}", json={**PESSOA, "is_active": False})
    assert client.get(API).json()["total"] == 1
    assert client.get(API, params={"inactive": True}).json()["total"] == 2


def test_permissoes(client: TestClient, db: Session) -> None:
    criar_usuario(db, "auditor@x.com", "auditor")
    entrar(client, "auditor@x.com")
    assert client.get(API).status_code == 200
    assert client.post(API, json=PESSOA).status_code == 403
