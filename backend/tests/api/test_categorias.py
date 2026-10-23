"""Categorias (árvore de até 3 níveis), status e códigos de resolução (F1-S3-01, F1-S3-02)."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from chamados.modules.audit.models import AuditLog
from tests.conftest import criar_usuario, entrar, grupo


def _admin(client: TestClient, db: Session) -> None:
    criar_usuario(db, "admin@exemplo.com", "admin", nome="Admin")
    entrar(client, "admin@exemplo.com")


def test_agente_lista_mas_nao_altera(client: TestClient, db: Session) -> None:
    criar_usuario(db, grupos={"TI": "supervisor"})
    entrar(client)
    for url in ("/api/v1/categories", "/api/v1/statuses", "/api/v1/resolution-codes"):
        assert client.get(url).status_code == 200
    assert client.post("/api/v1/categories", json={"name": "X"}).status_code == 403


def test_status_e_codigos_padrao(client: TestClient, db: Session) -> None:
    criar_usuario(db)
    entrar(client)
    status = client.get("/api/v1/statuses").json()["items"]
    assert [(s["name"], s["kind"]) for s in status] == [
        ("Pendente", "open"),
        ("Aguardando cliente", "waiting"),
        ("Entregue", "delivered"),
        ("Concluído", "closed"),
        ("Cancelado", "canceled"),
    ]
    codigos = client.get("/api/v1/resolution-codes").json()["items"]
    assert [c["name"] for c in codigos] == [
        "Feito",
        "Feito com solução de contorno",
        "Não reproduzível",
        "Fora do escopo do grupo",
    ]


def test_categoria_com_grupo_e_tipo_padrao(client: TestClient, db: Session) -> None:
    _admin(client, db)
    ti = grupo(db, "TI – Suporte")
    r = client.post(
        "/api/v1/categories",
        json={
            "name": "Acessos",
            "default_team_id": str(ti.public_id),
            "default_type": "request",
            "description": "Pedidos de acesso a sistemas e pastas",
        },
    )
    assert r.status_code == 201
    acessos = r.json()
    assert acessos["default_team_id"] == str(ti.public_id)
    assert acessos["default_type"] == "request"
    assert acessos["is_confidential"] is False

    r = client.patch(
        f"/api/v1/categories/{acessos['id']}",
        json={"is_confidential": True, "default_team_id": None, "description": None},
    )
    assert r.json()["is_confidential"] is True
    assert r.json()["default_team_id"] is None and r.json()["description"] is None
    acoes = db.scalars(
        select(AuditLog.action).where(AuditLog.target_type == "category").order_by(AuditLog.id)
    ).all()
    assert acoes == ["category.created", "category.updated"]

    r = client.post("/api/v1/categories", json={"name": "X", "default_team_id": acessos["id"]})
    assert r.status_code == 422


def test_arvore_de_ate_tres_niveis_sem_ciclos(client: TestClient, db: Session) -> None:
    _admin(client, db)

    def nova(nome: str, pai: dict[str, str] | None = None) -> dict[str, str]:
        r = client.post(
            "/api/v1/categories", json={"name": nome, "parent_id": pai["id"] if pai else None}
        )
        assert r.status_code == 201, r.text
        result: dict[str, str] = r.json()
        return result

    ti = nova("TI")
    acessos = nova("Acessos", ti)
    novo = nova("Novo acesso", acessos)
    assert novo["parent_id"] == acessos["id"]

    # 4º nível: não
    r = client.post("/api/v1/categories", json={"name": "Demais", "parent_id": novo["id"]})
    assert r.status_code == 422
    # Mesmo nome no mesmo nível: não; em outro nível: sim
    assert client.post("/api/v1/categories", json={"name": "TI"}).status_code == 409
    nova("Acessos")

    # Ciclo: TI abaixo de uma subcategoria dela
    r = client.patch(f"/api/v1/categories/{ti['id']}", json={"parent_id": novo["id"]})
    assert r.status_code == 422
    # Mover a subárvore Acessos (2 níveis) para baixo de outra de 2º nível passaria de 3
    rede = nova("Rede", ti)
    r = client.patch(f"/api/v1/categories/{acessos['id']}", json={"parent_id": rede["id"]})
    assert r.status_code == 422
    # Para a raiz: pode, mas lá já existe "Acessos"
    r = client.patch(f"/api/v1/categories/{acessos['id']}", json={"parent_id": None})
    assert r.status_code == 409

    r = client.patch(f"/api/v1/categories/{novo['id']}", json={"is_active": False})
    assert r.json()["is_active"] is False
    assert len(client.get("/api/v1/categories").json()["items"]) == 5
