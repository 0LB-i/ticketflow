"""Filas, novidades e busca (Sprint 4: docs/10 §10.6).

Cenário do test_chamados: Ana e Bia (supervisora) no TI, Caio na Infra.
"""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import entrar
from tests.test_chamados import API, base, cenario, criar_cliente, registrar  # noqa: F401


def numeros(client: TestClient, **query: Any) -> list[int]:
    r = client.get(API, params=query)
    assert r.status_code == 200, r.text
    return [t["number"] for t in r.json()["items"]]


def test_filas_e_contadores(client: TestClient, cenario: dict[str, Any]) -> None:  # noqa: F811
    da_bia = registrar(client, cenario, title="Com a Bia", assignee=cenario["bia"])["number"]
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
        json={
            **base(cenario),
            "title": "Da Infra",
            "team_id": cenario["infra"],
            "watcher_ids": [cenario["ana"]],
        },
    ).json()["number"]
    entrar(client, "ana@x.com")

    assert client.get(API, params={"view": "unassigned"}).status_code == 422
    assert client.get(API, params={"view": "news"}).status_code == 422
    assert numeros(client, view="mine") == [meu, parado]
    assert numeros(client, view="waiting") == [parado]
    assert numeros(client, view="watching") == [da_infra]
    assert set(numeros(client)) == {da_bia, meu, parado, concluido, da_infra}
    assert numeros(client, view="all", status=["closed"]) == [concluido]
    assert client.get(f"{API}/counts").json() == {
        "mine": 2,
        "waiting": 1,
        "watching": 1,
    }

    # Caio não vê as filas do TI
    entrar(client, "caio@x.com")
    assert numeros(client, view="mine") == [da_infra]
    assert client.get(f"{API}/counts").json()["waiting"] == 0


def test_novidade_e_comentario_de_outra_pessoa_depois_da_visita(
    client: TestClient,
    cenario: dict[str, Any],  # noqa: F811
) -> None:
    t = registrar(client, cenario, assignee="me")["number"]
    client.post(f"{API}/{t}/comments", json={"body": "Meu próprio comentário"})
    assert client.get(API).json()["items"][0]["has_news"] is False

    entrar(client, "bia@x.com")
    client.post(f"{API}/{t}/comments", json={"body": "Já trocou o toner?"})
    entrar(client, "ana@x.com")
    assert client.get(API).json()["items"][0]["has_news"] is True

    client.get(f"{API}/{t}")  # abrir o chamado é a visita
    assert client.get(API).json()["items"][0]["has_news"] is False


def test_novidade_com_varios_chamados_ja_visitados(
    client: TestClient,
    cenario: dict[str, Any],  # noqa: F811
) -> None:
    # A última visita é a do próprio chamado: com mais de uma visita, a consulta não pode
    # misturar os chamados (dava erro 500 na lista).
    lido = registrar(client, cenario, assignee="me")["number"]
    novo = registrar(client, cenario, assignee="me")["number"]
    client.get(f"{API}/{lido}")
    client.get(f"{API}/{novo}")
    entrar(client, "bia@x.com")
    client.post(f"{API}/{novo}/comments", json={"body": "Resolvido?"})
    entrar(client, "ana@x.com")
    novidades = {t["number"]: t["has_news"] for t in client.get(API).json()["items"]}
    assert novidades == {lido: False, novo: True}


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
    assert numeros(client, q="vpn", view="waiting") == []  # dentro da fila
    assert numeros(client, q="de") == []  # só palavras vazias
    assert client.get(API, params={"q": "?!"}).status_code == 200
    # "²" e "①" passam no isdigit(), mas não são número de chamado
    assert numeros(client, q="²") == []
    assert numeros(client, q="#①") == []
    assert client.get(f"{API}/²").status_code == 404

    entrar(client, "caio@x.com")  # a busca respeita a visibilidade
    assert numeros(client, q="impressora") == []
