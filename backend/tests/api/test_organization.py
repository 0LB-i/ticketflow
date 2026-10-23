"""Grupos (docs/08)."""

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
    assert client.post("/api/v1/teams", json={"name": "Novo"}).status_code == 403


def test_email_dos_membros_so_para_quem_administra_os_grupos(
    client: TestClient, db: Session
) -> None:
    """Todos leem a lista de grupos (formulários de chamado), mas só pelos nomes."""
    criar_usuario(db, grupos={"TI": "supervisor"})
    criar_usuario(db, "bia@exemplo.com", nome="Bia", grupos={"TI": "member"})
    entrar(client)
    membros = client.get("/api/v1/teams").json()["items"][0]["members"]
    assert {m["display_name"]: m["email"] for m in membros} == {"Ana Souza": None, "Bia": None}
    _admin(client, db)
    membros = client.get("/api/v1/teams").json()["items"][0]["members"]
    assert {m["email"] for m in membros} == {"ana@exemplo.com", "bia@exemplo.com"}


def test_usuario_excluido_nao_volta_a_um_grupo(client: TestClient, db: Session) -> None:
    _admin(client, db)
    ana = criar_usuario(db)
    team = client.post("/api/v1/teams", json={"name": "TI"}).json()
    assert client.delete(f"/api/v1/users/{ana.public_id}").status_code == 204
    r = client.put(f"/api/v1/teams/{team['id']}/members/{ana.public_id}", json={"role": "member"})
    assert r.status_code == 404
    assert client.get("/api/v1/teams").json()["items"][0]["members"] == []


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
