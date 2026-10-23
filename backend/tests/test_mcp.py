"""Servidor MCP em /mcp (modules/mcp_server): ferramentas sobre os mesmos services da API, com o
token de API da pessoa."""

from itertools import count
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from chamados.modules.tickets.models import Ticket, TicketRead
from tests.test_chamados import cenario, eventos, registrar  # noqa: F401
from tests.test_tokens_api import criar_token

ACCEPT = "application/json, text/event-stream"
_ids = count(1)


def _rpc(client: TestClient, raw: str, method: str, params: dict[str, Any] | None = None) -> Any:
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": next(_ids), "method": method, "params": params or {}},
        headers={"Authorization": f"Bearer {raw}", "Accept": ACCEPT},
    )
    assert r.status_code == 200, r.text
    return r.json()["result"]


def ferramenta(client: TestClient, raw: str, nome: str, **args: Any) -> dict[str, Any]:
    result = _rpc(client, raw, "tools/call", {"name": nome, "arguments": args})
    assert not result["isError"], result["content"][0]["text"]
    structured: dict[str, Any] = result["structuredContent"]
    return structured


def erro(client: TestClient, raw: str, nome: str, **args: Any) -> str:
    result = _rpc(client, raw, "tools/call", {"name": nome, "arguments": args})
    assert result["isError"]
    text: str = result["content"][0]["text"]
    # O SDK põe o nome da ferramenta na frente da mensagem.
    return text.removeprefix(f"Error executing tool {nome}: ")


def test_sem_token_valido_a_rota_recusa(client: TestClient) -> None:
    for header in ({}, {"Authorization": "Bearer tf_errado"}):
        r = client.post("/mcp", json={}, headers={"Accept": ACCEPT, **header})
        assert r.status_code == 401
        assert r.headers["www-authenticate"] == "Bearer"


def test_ferramentas_anunciadas(
    client: TestClient,
    cenario: dict[str, Any],  # noqa: F811
    db: Session,
) -> None:
    raw = criar_token(db, "ana@x.com", "read")
    assert (
        "Você age em nome da pessoa"
        in _rpc(
            client,
            raw,
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "teste", "version": "1"},
            },
        )["instructions"]
    )
    tools = {t["name"]: t for t in _rpc(client, raw, "tools/list")["tools"]}
    leitura = {"list_tickets", "get_ticket", "get_ticket_history", "list_options", "search_clients"}
    escrita = {"create_ticket", "add_task", "change_status", "assign_ticket", "transfer_ticket"}
    escrita |= {"cancel_ticket"}
    assert set(tools) == leitura | escrita
    assert all(tools[n]["annotations"]["readOnlyHint"] for n in leitura)
    assert not any(tools[n]["annotations"]["readOnlyHint"] for n in escrita)
    destrutivas = {n for n in escrita if tools[n]["annotations"]["destructiveHint"]}
    assert destrutivas == {"cancel_ticket"}


def test_leitura_com_a_visibilidade_da_pessoa(
    client: TestClient,
    cenario: dict[str, Any],  # noqa: F811
    db: Session,
) -> None:
    numero = registrar(client, cenario, description="Papel **atolado**")["number"]
    client.post(f"/api/v1/tickets/{numero}/comments", json={"body": "Troquei o rolo"})
    client.cookies.clear()
    ana = criar_token(db, "ana@x.com", "read")

    lista = ferramenta(client, ana, "list_tickets", query="impressora")
    assert [t["number"] for t in lista["items"]] == [numero]
    lido = ferramenta(client, ana, "get_ticket", number=numero)
    assert lido["ticket"]["description"] == "Papel **atolado**"
    assert [t["body"] for t in lido["tasks"]] == ["Troquei o rolo"]
    assert "comment" in lido["ticket"]["allowed_actions"]
    # O assistente lê sem contar como visita da pessoa (o aviso de novidade continua)
    assert db.scalar(select(func.count()).select_from(TicketRead)) == 0
    historico = ferramenta(client, ana, "get_ticket_history", number=numero)
    assert historico["items"][0]["type"] == "ticket.created"
    opcoes = ferramenta(client, ana, "list_options")
    assert {s["kind"] for s in opcoes["statuses"]} >= {"open", "closed"}
    assert [t["name"] for t in opcoes["teams"] if t["i_am_member"]] == ["TI"]
    clientes = ferramenta(client, ana, "search_clients", query="padrão")
    assert [c["id"] for c in clientes["items"]] == [cenario["cliente"]]

    # O Caio, da Infra, não vê o chamado do TI
    caio = criar_token(db, "caio@x.com", "read")
    assert erro(client, caio, "get_ticket", number=numero) == "Você não tem acesso a este chamado."
    assert ferramenta(client, caio, "list_tickets")["items"] == []


def test_escrita_registra_comenta_e_muda_o_status(
    client: TestClient,
    cenario: dict[str, Any],  # noqa: F811
    db: Session,
) -> None:
    client.cookies.clear()
    ana = criar_token(db, "ana@x.com")
    dados = {
        "title": "Sem rede no 2º andar",
        "client_id": cenario["cliente"],
        "team_id": cenario["ti"],
        "request_id": "pedido-1",
    }
    criado = ferramenta(client, ana, "create_ticket", **dados)
    assert criado["assignee"]["display_name"] == "Ana"
    # Repetir com o mesmo request_id devolve o mesmo chamado, sem registrar de novo
    assert ferramenta(client, ana, "create_ticket", **dados)["number"] == criado["number"]
    assert db.scalar(select(func.count()).select_from(Ticket)) == 1
    outro = erro(client, ana, "create_ticket", **{**dados, "title": "Outro título"})
    assert outro == "Este request_id já foi usado com outros dados."

    numero = criado["number"]
    tarefa = ferramenta(
        client, ana, "add_task", number=numero, body="Reiniciei o switch", time_spent_minutes=15
    )
    assert tarefa["time_spent_minutes"] == 15
    mudou = ferramenta(client, ana, "change_status", number=numero, status_id=2)
    assert mudou["status"]["kind"] == "waiting"

    client.headers["Authorization"] = f"Bearer {ana}"
    tipos = {e["type"]: e for e in eventos(client, numero)}
    assert tipos["ticket.created"]["payload"]["via"] == "mcp"
    assert tipos["ticket.status_changed"]["payload"]["via"] == "mcp"


def test_token_de_leitura_nao_altera(
    client: TestClient,
    cenario: dict[str, Any],  # noqa: F811
    db: Session,
) -> None:
    numero = registrar(client, cenario)["number"]
    client.cookies.clear()
    ana = criar_token(db, "ana@x.com", "read")
    assert erro(client, ana, "add_task", number=numero, body="Não pode") == (
        "Este token de API só permite leitura."
    )


def test_recusa_da_regra_vem_no_idioma_da_pessoa(
    client: TestClient,
    cenario: dict[str, Any],  # noqa: F811
    db: Session,
) -> None:
    numero = registrar(client, cenario)["number"]
    client.patch("/api/v1/me", json={"locale": "en"})
    client.cookies.clear()
    ana = criar_token(db, "ana@x.com")
    assert erro(client, ana, "change_status", number=numero, status_id=999) == "Status not found."


def test_atribuir_transferir_e_cancelar(
    client: TestClient,
    cenario: dict[str, Any],  # noqa: F811
    db: Session,
) -> None:
    numero = registrar(client, cenario)["number"]  # da Ana, no TI
    client.cookies.clear()
    ana = criar_token(db, "ana@x.com")

    # add: a Bia entra como mais uma responsável; repetir não muda nada
    for _ in range(2):
        r = ferramenta(
            client, ana, "assign_ticket", number=numero, assignee=cenario["bia"], mode="add"
        )
    assert r["assignee"]["display_name"] == "Ana"
    assert [c["display_name"] for c in r["co_assignees"]] == ["Bia"]
    # main: a Bia vira a principal, no lugar da Ana
    r = ferramenta(client, ana, "assign_ticket", number=numero, assignee=cenario["bia"])
    assert r["assignee"]["display_name"] == "Bia" and r["co_assignees"] == []
    # "me": a Ana assume de volta
    r = ferramenta(client, ana, "assign_ticket", number=numero, assignee="me")
    assert r["assignee"]["display_name"] == "Ana"
    texto = erro(client, ana, "assign_ticket", number=numero, assignee=cenario["caio"])
    assert texto == "O responsável precisa ser um membro ativo do grupo."

    # Transferir para a Infra, com o Caio; a Ana deixa de poder alterar
    r = ferramenta(
        client,
        ana,
        "transfer_ticket",
        number=numero,
        team_id=cenario["infra"],
        assignee_id=cenario["caio"],
        reason="É da rede",
    )
    assert r["team"]["name"] == "Infra" and r["assignee"]["display_name"] == "Caio"
    assert (
        erro(client, ana, "cancel_ticket", number=numero)
        == "Você não tem permissão para esta ação."
    )

    # O Caio cancela; repetir não dá erro
    caio = criar_token(db, "caio@x.com")
    for _ in range(2):
        r = ferramenta(client, caio, "cancel_ticket", number=numero, comment="Duplicado do #999")
        assert r["status"]["kind"] == "canceled"
    client.headers["Authorization"] = f"Bearer {caio}"
    tipos = [e["type"] for e in eventos(client, numero)]
    assert tipos.count("ticket.status_changed") == 1
    assert "ticket.transferred" in tipos


def test_cancelar_com_token_de_leitura(
    client: TestClient,
    cenario: dict[str, Any],  # noqa: F811
    db: Session,
) -> None:
    numero = registrar(client, cenario)["number"]
    client.cookies.clear()
    ana = criar_token(db, "ana@x.com", "read")
    assert (
        erro(client, ana, "cancel_ticket", number=numero) == "Este token de API só permite leitura."
    )
