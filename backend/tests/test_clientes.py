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
    "emails": ["Joao@Exemplo.com", "joao@exemplo.com", "joao.silva@exemplo.com"],
    "phones": ["(11) 3333-4444", "+55 11 98765-4321"],
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
    "emails": ["contato@paoquente.com.br"],
    "phones": ["1133334444"],
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
    assert c["emails"] == ["joao@exemplo.com", "joao.silva@exemplo.com"]  # sem repetidos
    assert c["phones"] == ["1133334444", "11987654321"]
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
        ({"kind": "company", "trade_name": "Loja"}, "CNPJ inválido."),
        ({"phones": ["3333-4444"]}, "Telefone inválido: informe o DDD e o número."),
        ({"phones": ["11987654321", "123"]}, "Telefone inválido: informe o DDD e o número."),
        ({"postal_code": "1310-100"}, "CEP inválido: são 8 números."),
        ({"state": "XX"}, "UF inválida."),
        ({"city": "  "}, "Informe a cidade."),
        ({"birth_date": "2999-01-01"}, "A data de nascimento não pode ficar no futuro."),
    ],
)
def test_validacoes(
    client: TestClient, agente: None, mudanca: dict[str, Any], mensagem: str
) -> None:
    r = client.post(API, json={**PESSOA, **mudanca})
    assert r.status_code == 422
    assert r.json()["detail"] == mensagem


def test_email_valido(client: TestClient, agente: None) -> None:
    assert client.post(API, json={**PESSOA, "emails": ["joao"]}).status_code == 422


def test_campos_obrigatorios_por_tipo(client: TestClient, agente: None) -> None:
    endereco = {"postal_code": "01310100", "city": "São Paulo", "state": "SP"}
    pf = {"kind": "person", "name": "João da Silva", "document": "52998224725", **endereco}
    pj = {
        "kind": "company",
        "name": "Padaria Pão Quente Ltda",
        "trade_name": "Pão Quente",
        "document": "12ABC34501DE35",
        **endereco,
    }
    for base, obrigatorios in (
        (pf, ("name", "document")),
        (pj, ("name", "trade_name", "document")),
    ):
        for campo in (*obrigatorios, "postal_code", "city", "state"):
            sem = {k: v for k, v in base.items() if k != campo}
            assert client.post(API, json=sem).status_code == 422, (base["kind"], campo)
            branco = {**base, campo: "  "}
            assert client.post(API, json=branco).status_code == 422, (base["kind"], campo)
    r = client.post(API, json={k: v for k, v in pj.items() if k != "document"})
    assert r.json()["detail"] == "Informe o CNPJ."
    # O resto (endereço, contatos, RG, IE...) continua opcional
    for base in (pf, pj):
        r = client.post(API, json=base)
        assert r.status_code == 201, r.text
        assert r.json()["street"] is None and r.json()["emails"] == [] and r.json()["phones"] == []


def test_documento_repetido_e_edicao(client: TestClient, db: Session, agente: None) -> None:
    c = client.post(API, json=PESSOA).json()
    # O mesmo CPF (e os mesmos dados) pode estar em mais de um cadastro
    r = client.post(API, json={**PESSOA, "document": "52998224725"})
    assert r.status_code == 201, r.text
    outro = client.post(API, json={**PESSOA, "document": "11144477735"}).json()
    r = client.put(f"{API}/{outro['id']}", json=PESSOA)
    assert r.status_code == 200 and r.json()["document"] == "52998224725"
    assert client.get(API, params={"q": "529.982"}).json()["total"] == 3

    r = client.put(f"{API}/{c['id']}", json={**PESSOA, "city": "Campinas", "is_active": False})
    assert r.status_code == 200
    assert r.json()["city"] == "Campinas" and r.json()["is_active"] is False
    log = db.scalars(
        select(AuditLog).where(AuditLog.action == "client.updated", AuditLog.target_id == c["id"])
    ).one()
    assert log.after == {"fields": ["city", "is_active"]}

    # Sem mudança, sem auditoria
    client.put(f"{API}/{c['id']}", json={**PESSOA, "city": "Campinas", "is_active": False})
    assert len(db.scalars(select(AuditLog).where(AuditLog.action == "client.updated")).all()) == 2


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
    assert client.get(API, params={"q": "joao.silva@"}).json()["total"] == 1

    client.put(f"{API}/{pessoa['id']}", json={**PESSOA, "is_active": False})
    assert client.get(API).json()["total"] == 1
    assert client.get(API, params={"inactive": True}).json()["total"] == 2


def test_permissoes(client: TestClient, db: Session) -> None:
    criar_usuario(db, "auditor@x.com", "auditor")
    entrar(client, "auditor@x.com")
    assert client.get(API).status_code == 200
    assert client.post(API, json=PESSOA).status_code == 403
