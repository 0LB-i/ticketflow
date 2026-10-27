"""Tela do servidor do cadastro de clientes (ADR 0011)."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from chamados.modules.clients.models import Client
from tests.apoio import EMPRESA, ENDERECO, PESSOA
from tests.conftest import criar_usuario, entrar

API = "/api/v1/clients"


def _form(client: TestClient, dados: dict[str, Any]) -> dict[str, Any]:
    return {"csrf_token": client.cookies["tf_csrf"], **dados}


def _admin_de_clientes(client: TestClient, db: Session) -> None:
    criar_usuario(db, "ana@x.com", grupos={"Administradores": "member"})
    entrar(client, "ana@x.com")


def test_so_o_grupo_administradores(client: TestClient, db: Session) -> None:
    criar_usuario(db, "bia@x.com", "admin", grupos={"TI": "member"})
    entrar(client, "bia@x.com")
    for url in ("/admin/clientes", "/admin/clientes/novo"):
        r = client.get(url)
        assert r.status_code == 403, url
        assert "Você não tem permissão para esta ação." in r.text
    # Mesmo enviando o formulário direto: a API confere numa dependência que a tela não usa.
    r = client.post("/admin/clientes/novo", data=_form(client, PESSOA))
    assert r.status_code == 403
    assert client.get(API).status_code == 403


def test_lista_e_filtros(client: TestClient, db: Session) -> None:
    _admin_de_clientes(client, db)
    client.post(API, json=PESSOA)
    client.post(API, json=EMPRESA)
    r = client.get("/admin/clientes")
    assert r.status_code == 200
    assert "João da Silva" in r.text and "Pão Quente" in r.text
    assert "529.982.247-25" in r.text  # documento formatado
    assert "(11) 3333-4444" in r.text
    assert "2 cliente(s)" in r.text
    assert "Pão Quente" not in client.get("/admin/clientes?tipo=person").text
    assert "João da Silva" not in client.get("/admin/clientes?q=paoquente").text
    assert "Nenhum registro encontrado." in client.get("/admin/clientes?uf=RJ").text


def test_cadastro_confere_todos_os_campos(client: TestClient, db: Session) -> None:
    _admin_de_clientes(client, db)
    dados = {
        "kind": "person",
        "name": "",
        "document": "529.982.247-24",
        "postal_code": "0131",
        "city": "",
        "state": "",
        "phones": ["(11) 3333"],
        "emails": ["sem-arroba"],
    }
    r = client.post("/admin/clientes/novo", data=_form(client, dados))
    assert r.status_code == 422
    for texto in (
        "Campo obrigatório.",
        "CPF inválido.",
        "O CEP tem 8 números.",
        "Escolha a UF.",
        "Informe o DDD e o número.",
        "Informe um e-mail válido.",
    ):
        assert texto in r.text, texto
    assert 'value="529.982.247-24"' in r.text  # o que foi digitado continua


def test_cadastro_e_edicao(client: TestClient, db: Session) -> None:
    _admin_de_clientes(client, db)
    dados = {**EMPRESA, "phones": ["(11) 3333-4444", ""], "emails": ["contato@paoquente.com.br"]}
    r = client.post("/admin/clientes/novo", data=_form(client, dados), follow_redirects=False)
    assert r.headers["location"] == "/admin/clientes"
    assert "Cliente cadastrado" in client.get("/admin/clientes").text
    cliente = db.scalar(select(Client).where(Client.trade_name == "Pão Quente"))
    assert cliente is not None
    assert cliente.document == "12ABC34501DE35"
    assert cliente.phones == ["1133334444"]
    assert cliente.state_registration == "ISENTO"

    r = client.get(f"/admin/clientes/{cliente.public_id}")
    assert 'value="12.ABC.345/01DE-35"' in r.text
    assert 'value="01310-100"' in r.text
    alterado = {**dados, "contact_name": "João", "is_active": ""}  # desmarca "ativo"
    r = client.post(f"/admin/clientes/{cliente.public_id}", data=_form(client, alterado))
    assert "Alterações salvas" in r.text
    db.refresh(cliente)
    assert cliente.contact_name == "João"
    assert not cliente.is_active


def test_contrato(client: TestClient, db: Session) -> None:
    """As horas aparecem e valem só no contrato mensal ou anual."""
    _admin_de_clientes(client, db)
    r = client.get("/admin/clientes/novo")
    assert '<fieldset data-se-contrato="monthly annual" class="min-w-0" hidden disabled>' in r.text
    dados = {**PESSOA, "contract_type": "annual", "contract_hours": ""}
    r = client.post("/admin/clientes/novo", data=_form(client, dados))
    assert r.status_code == 422
    assert "Campo obrigatório." in r.text
    assert '<fieldset data-se-contrato="monthly annual" class="min-w-0">' in r.text
    r = client.post("/admin/clientes/novo", data=_form(client, {**dados, "contract_hours": "2,5"}))
    assert "Informe um número inteiro de 1 a 10.000." in r.text
    dados["contract_hours"] = "240"
    r = client.post("/admin/clientes/novo", data=_form(client, dados), follow_redirects=False)
    assert r.status_code == 303
    cliente = db.scalar(select(Client).where(Client.name == "João da Silva"))
    assert cliente is not None
    assert (cliente.contract_type, cliente.contract_hours) == ("annual", 240)
    r = client.get(f"/admin/clientes/{cliente.public_id}")
    assert 'value="annual" checked' in r.text and 'value="240"' in r.text
    # Avulso: as horas digitadas antes não vão junto.
    avulso = {**dados, "contract_type": "on_demand", "is_active": "1"}
    client.post(f"/admin/clientes/{cliente.public_id}", data=_form(client, avulso))
    db.refresh(cliente)
    assert (cliente.contract_type, cliente.contract_hours) == ("on_demand", None)


def test_documento_repetido_mostra_o_erro_da_api(client: TestClient, db: Session) -> None:
    _admin_de_clientes(client, db)
    client.post(API, json=PESSOA)
    outro = {**PESSOA, "name": "Outro nome", "emails": [], "phones": [], **ENDERECO}
    r = client.post("/admin/clientes/novo", data=_form(client, outro))
    assert r.status_code == 422
    assert "Já existe um cliente com este CPF/CNPJ." in r.text


def test_campos_do_outro_tipo_nao_bloqueiam_o_envio(client: TestClient, db: Session) -> None:
    """O nome fantasia é obrigatório só para PJ: no formulário de PF ele fica num fieldset
    desativado, que o navegador não valida nem envia."""
    _admin_de_clientes(client, db)
    r = client.get("/admin/clientes/novo")
    assert '<fieldset data-se-tipo="company" class="min-w-0" hidden disabled>' in r.text
    assert '<fieldset data-se-tipo="person" class="min-w-0">' in r.text


def test_id_invalido_e_email_recusado(client: TestClient, db: Session) -> None:
    _admin_de_clientes(client, db)
    assert client.get("/admin/clientes/abc").status_code == 404
    dados = {**PESSOA, "emails": ["ok@exemplo.com", "", "a@b..com"]}
    r = client.post("/admin/clientes/novo", data=_form(client, dados))
    assert r.status_code == 422
    # A 3ª linha (a 2ª está vazia) é a marcada.
    assert r.text.count("Informe um e-mail válido.") == 1
    assert 'value="a@b..com" autocomplete="off" aria-invalid="true"' in r.text


def test_texto_longo_demais_marca_o_campo(client: TestClient, db: Session) -> None:
    _admin_de_clientes(client, db)
    r = client.post("/admin/clientes/novo", data=_form(client, {**PESSOA, "street": "x" * 201}))
    assert r.status_code == 422
    assert "Texto longo demais." in r.text
    assert "Algo deu errado" not in r.text
