"""Status personalizados em Configurações (F1-S5-02): criar, renomear, ordenar e remover."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from chamados.modules.audit.models import AuditLog
from tests.conftest import criar_usuario, entrar, grupo
from tests.test_chamados import criar_cliente

API = "/api/v1/statuses"


@pytest.fixture(autouse=True)
def status_originais(db: Session) -> Iterator[None]:
    """Os status vêm da migração e o TRUNCATE dos testes não os recria: volta como estavam."""
    linhas = db.execute(text("SELECT * FROM ticket_statuses")).mappings().all()
    yield
    db.rollback()
    db.execute(text("TRUNCATE tickets CASCADE"))
    db.execute(text("DELETE FROM ticket_statuses"))
    for linha in linhas:
        db.execute(
            text(
                "INSERT INTO ticket_statuses (id, name, kind, sort_order, is_default_for_kind) "
                "OVERRIDING SYSTEM VALUE VALUES (:id, :name, :kind, :sort_order, "
                ":is_default_for_kind)"
            ),
            dict(linha),
        )
    db.commit()


def nomes(r: Any) -> list[str]:
    return [s["name"] for s in r.json()["items"]]


def por_nome(client: TestClient) -> dict[str, dict[str, Any]]:
    return {s["name"]: s for s in client.get(API).json()["items"]}


def test_padrao_e_permissao(client: TestClient, db: Session) -> None:
    criar_usuario(db, "ana@x.com")
    entrar(client, "ana@x.com")
    r = client.get(API)
    assert nomes(r) == [
        "Pendente",
        "Aguardando cliente",
        "Entregue",
        "Concluído",
        "Cancelado",
    ]
    assert [s["is_default"] for s in r.json()["items"]] == [True, True, True, True, True]
    # Agente lista, mas não altera
    assert client.post(API, json={"name": "Em teste", "kind": "open"}).status_code == 403


def test_criar_renomear_ordenar(client: TestClient, db: Session) -> None:
    criar_usuario(db, "admin@x.com", "admin")
    entrar(client, "admin@x.com")

    r = client.post(API, json={"name": " Em teste ", "kind": "open"})
    assert r.status_code == 201
    assert nomes(r)[-1] == "Em teste"
    novo = por_nome(client)["Em teste"]
    assert novo["kind"] == "open" and novo["is_default"] is False
    assert client.post(API, json={"name": "em TESTE", "kind": "closed"}).status_code == 422
    assert client.post(API, json={"name": "Aprovação", "kind": "approval"}).status_code == 422

    r = client.patch(f"{API}/{novo['id']}", json={"name": "Em homologação"})
    assert "Em homologação" in nomes(r)
    assert client.patch(f"{API}/{novo['id']}", json={"name": "Pendente"}).status_code == 422

    ids = [s["id"] for s in client.get(API).json()["items"]]
    nova_ordem = [ids[-1], *ids[:-1]]
    r = client.put(f"{API}/order", json={"ids": nova_ordem})
    assert [s["id"] for s in r.json()["items"]] == nova_ordem
    assert client.put(f"{API}/order", json={"ids": ids[:-1]}).status_code == 422

    acoes = db.scalars(select(AuditLog.action).where(AuditLog.target_type == "ticket_status")).all()
    assert acoes == ["ticket_status.created", "ticket_status.updated"]


def test_remover_move_os_chamados(client: TestClient, db: Session) -> None:
    criar_usuario(db, "admin@x.com", "admin", grupos={"TI": "member"})
    entrar(client, "admin@x.com")
    ti = str(grupo(db, "TI").public_id)
    base = {"client_id": criar_cliente(db, "Cliente", "33445566000186"), "assignee": "me"}
    status = por_nome(client)

    # O único status de um comportamento não sai
    r = client.delete(f"{API}/{status['Cancelado']['id']}")
    assert r.status_code == 422

    # Entregue é o único do seu comportamento: também não sai
    assert client.delete(f"{API}/{status['Entregue']['id']}").status_code == 422

    # Um status que não é o padrão: os chamados vão para o padrão do kind (Entregue)
    revisao = client.post(API, json={"name": "Em revisão", "kind": "delivered"}).json()
    revisao_id = next(s["id"] for s in revisao["items"] if s["name"] == "Em revisão")
    t = client.post(
        "/api/v1/tickets",
        json={**base, "title": "Revisar", "team_id": ti, "status_id": revisao_id},
    ).json()
    assert por_nome(client)["Em revisão"]["ticket_count"] == 1
    r = client.delete(f"{API}/{revisao_id}")
    assert r.status_code == 200 and "Em revisão" not in nomes(r)
    assert client.get(f"/api/v1/tickets/{t['number']}").json()["status"]["name"] == "Entregue"
    assert por_nome(client)["Entregue"]["ticket_count"] == 1

    # Removendo o padrão, o próximo do mesmo kind assume (e recebe os chamados)
    client.post(API, json={"name": "Em andamento", "kind": "open"})
    client.post("/api/v1/tickets", json={**base, "title": "Pendente", "team_id": ti})
    r = client.delete(f"{API}/{status['Pendente']['id']}")
    andamento = por_nome(client)["Em andamento"]
    assert andamento["is_default"] is True and andamento["ticket_count"] == 1
    # E o registro passa a usar o novo padrão
    t = client.post("/api/v1/tickets", json={**base, "title": "Novo", "team_id": ti}).json()
    assert t["status"]["name"] == "Em andamento"
