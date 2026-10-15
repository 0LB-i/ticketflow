"""Grupos e setores atendidos (docs/08)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import criar_usuario, entrar


def _admin(client: TestClient, db: Session) -> None:
    criar_usuario(db, "admin@exemplo.com", "admin", nome="Admin")
    entrar(client, "admin@exemplo.com")


def test_agente_lista_mas_nao_altera(client: TestClient, db: Session) -> None:
    criar_usuario(db, grupos={"TI": "supervisor"})
    entrar(client)
    assert client.get("/api/v1/teams").status_code == 200
    assert client.get("/api/v1/departments").status_code == 200
    assert client.post("/api/v1/teams", json={"name": "Novo"}).status_code == 403
    assert client.post("/api/v1/departments", json={"name": "Novo"}).status_code == 403


def test_grupo_e_membros(client: TestClient, db: Session) -> None:
    _admin(client, db)
    ana = criar_usuario(db)
    team = client.post("/api/v1/teams", json={"name": "TI – Suporte"}).json()
    assert client.post("/api/v1/teams", json={"name": "TI – Suporte"}).status_code == 409

    url = f"/api/v1/teams/{team['id']}/members/{ana.public_id}"
    r = client.put(url, json={"role": "supervisor"})
    assert r.json()["members"] == [
        {
            "user_id": str(ana.public_id),
            "display_name": "Ana Souza",
            "email": "ana@exemplo.com",
            "role": "supervisor",
            "is_active": True,
        }
    ]
    r = client.put(url, json={"role": "member"})
    assert r.json()["members"][0]["role"] == "member"
    assert client.delete(url).json()["members"] == []
    assert client.delete(url).status_code == 404

    r = client.patch(f"/api/v1/teams/{team['id']}", json={"is_active": False, "name": "TI"})
    assert r.json()["is_active"] is False and r.json()["name"] == "TI"


def test_setores_em_arvore_sem_ciclos(client: TestClient, db: Session) -> None:
    _admin(client, db)
    adm = client.post("/api/v1/departments", json={"name": "Administrativo"}).json()
    fin = client.post(
        "/api/v1/departments", json={"name": "Financeiro", "parent_id": adm["id"], "code": "FIN"}
    ).json()
    assert fin["parent_id"] == adm["id"]
    contas = client.post(
        "/api/v1/departments", json={"name": "Contas a Pagar", "parent_id": fin["id"]}
    ).json()

    # Mesmo nome no mesmo nível: não; em outro nível: sim
    assert client.post("/api/v1/departments", json={"name": "Administrativo"}).status_code == 409
    r = client.post("/api/v1/departments", json={"name": "Financeiro"})
    assert r.status_code == 201
    assert client.post("/api/v1/departments", json={"name": "X", "code": "FIN"}).status_code == 409

    # Ciclo: Administrativo abaixo de um subsetor dele
    r = client.patch(f"/api/v1/departments/{adm['id']}", json={"parent_id": contas["id"]})
    assert r.status_code == 422
    r = client.patch(f"/api/v1/departments/{contas['id']}", json={"parent_id": None})
    assert r.json()["parent_id"] is None


def test_membro_sem_email(client: TestClient, db: Session) -> None:
    """O administrador padrão (só usuário "admin") também pode ser membro de um grupo."""
    criar_usuario(db, None, "admin", username="admin", grupos={"TI": "member"})
    entrar(client, "admin")
    membros = client.get("/api/v1/teams").json()["items"][0]["members"]
    assert membros[0]["email"] is None


def test_nulo_nos_campos_obrigatorios_e_ignorado(client: TestClient, db: Session) -> None:
    _admin(client, db)
    team = client.post("/api/v1/teams", json={"name": "TI", "description": "Suporte"}).json()
    url = f"/api/v1/teams/{team['id']}"
    r = client.patch(url, json={"name": None, "is_active": None, "notify_on_new": None})
    assert r.status_code == 200
    assert (r.json()["name"], r.json()["is_active"]) == ("TI", True)
    assert client.patch(url, json={"description": None}).json()["description"] is None

    dept = client.post("/api/v1/departments", json={"name": "Financeiro"}).json()
    r = client.patch(f"/api/v1/departments/{dept['id']}", json={"name": None, "is_active": None})
    assert r.status_code == 200
    assert (r.json()["name"], r.json()["is_active"]) == ("Financeiro", True)


def test_renomear_setor_para_nome_existente(client: TestClient, db: Session) -> None:
    _admin(client, db)
    client.post("/api/v1/departments", json={"name": "Compras"})
    vendas = client.post("/api/v1/departments", json={"name": "Vendas"}).json()
    r = client.patch(f"/api/v1/departments/{vendas['id']}", json={"name": "Compras"})
    assert r.status_code == 409
