"""Filas, novidades, busca e "Pegar o próximo" (Sprint 4: docs/10 §10.6).

Cenário do test_chamados: Ana e Bia (supervisora) no TI, Caio na Infra.
"""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import entrar
from tests.test_chamados import API, cenario, criar_cliente, registrar  # noqa: F401


def numeros(client: TestClient, **query: Any) -> list[int]:
    r = client.get(API, params=query)
    assert r.status_code == 200, r.text
    return [t["number"] for t in r.json()["items"]]


def test_filas_e_contadores(client: TestClient, cenario: dict[str, Any]) -> None:  # noqa: F811
    fila = registrar(client, cenario, title="Na fila")["number"]
    meu = registrar(client, cenario, title="Comigo", assignee="me")["number"]
    parado = registrar(client, cenario, title="Parado", assignee="me")["number"]
    client.post(f"{API}/{parado}/transitions", json={"action": "wait", "comment": "Esperando"})
    concluido = registrar(client, cenario, title="Feito", assignee="me")["number"]
    client.post(
        f"{API}/{concluido}/transitions",
        json={"action": "close", "comment": "Pronto", "resolution_code_id": 1},
    )
    entrar(client, "caio@x.com")
    da_infra = client.post(
        API,
        json={"title": "Da Infra", "team_id": cenario["infra"], "watcher_ids": [cenario["ana"]]},
    ).json()["number"]
    entrar(client, "ana@x.com")

    assert numeros(client, view="unassigned") == [fila]
    assert numeros(client, view="mine") == [meu, parado]
    assert numeros(client, view="waiting") == [parado]
    assert numeros(client, view="watching") == [da_infra]
    assert set(numeros(client)) == {fila, meu, parado, concluido, da_infra}
    assert numeros(client, view="all", status=["closed"]) == [concluido]
    assert client.get(f"{API}/counts").json() == {
        "unassigned": 1,
        "mine": 2,
        "news": 0,
        "waiting": 1,
        "watching": 1,
    }

    # Caio não vê as filas do TI
    entrar(client, "caio@x.com")
    assert numeros(client, view="unassigned") == [da_infra]
    assert client.get(f"{API}/counts").json()["unassigned"] == 1


def test_novidade_e_comentario_de_outra_pessoa_depois_da_visita(
    client: TestClient,
    cenario: dict[str, Any],  # noqa: F811
) -> None:
    t = registrar(client, cenario, assignee="me")["number"]
    client.post(f"{API}/{t}/comments", json={"body": "Meu próprio comentário"})
    assert numeros(client, view="news") == []

    entrar(client, "bia@x.com")
    client.post(f"{API}/{t}/comments", json={"body": "Já trocou o toner?"})
    entrar(client, "ana@x.com")
    assert numeros(client, view="news") == [t]
    assert client.get(API).json()["items"][0]["has_news"] is True
    assert client.get(f"{API}/counts").json()["news"] == 1

    client.get(f"{API}/{t}")  # abrir o chamado é a visita
    assert numeros(client, view="news") == []
    assert client.get(API).json()["items"][0]["has_news"] is False


def test_busca(client: TestClient, cenario: dict[str, Any], db: Session) -> None:  # noqa: F811
    padaria = criar_cliente(db, "Padaria Pão Quente", "11222333000181")
    impressora = registrar(client, cenario, title="Impressora não imprime", client_id=padaria)
    vpn = registrar(
        client, cenario, title="VPN do Rui", description="Não conecta de casa", assignee="me"
    )
    client.post(f"{API}/{vpn['number']}/comments", json={"body": "Certificado expirado"})

    assert numeros(client, q="impressora") == [impressora["number"]]
    assert numeros(client, q="imprim") == [impressora["number"]]  # começo de palavra
    assert numeros(client, q="conexão casa") == []  # todas as palavras
    assert numeros(client, q="conecta CASA") == [vpn["number"]]  # descrição
    assert numeros(client, q="certificados") == [vpn["number"]]  # comentário, plural
    assert numeros(client, q="pao quente") == [impressora["number"]]  # cliente, sem acento
    assert numeros(client, q=f"#{vpn['number']}") == [vpn["number"]]
    assert numeros(client, q="vpn", view="unassigned") == []  # dentro da fila
    assert numeros(client, q="de") == []  # só palavras vazias
    assert client.get(API, params={"q": "?!"}).status_code == 200

    entrar(client, "caio@x.com")  # a busca respeita a visibilidade
    assert numeros(client, q="impressora") == []


def test_pegar_o_proximo(client: TestClient, cenario: dict[str, Any]) -> None:  # noqa: F811
    primeiro = registrar(client, cenario, title="Primeiro")["number"]
    segundo = registrar(client, cenario, title="Segundo")["number"]

    entrar(client, "caio@x.com")
    r = client.post(f"{API}/next", json={})
    assert r.status_code == 404 and r.json()["detail"] == "Não há chamados na fila."

    entrar(client, "bia@x.com")
    r = client.post(f"{API}/next", json={"team_id": cenario["ti"]})
    assert r.status_code == 200
    assert r.json()["number"] == primeiro and r.json()["assignee"]["display_name"] == "Bia"
    assert client.post(f"{API}/next", json={}).json()["number"] == segundo
    assert client.post(f"{API}/next", json={}).status_code == 404

    entrar(client, "auditor@x.com")  # sem grupos, não há fila
    assert client.post(f"{API}/next", json={}).status_code == 404
