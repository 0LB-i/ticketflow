"""Administração de usuários (docs/13: /admin/usuarios)."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from chamados.modules.audit.models import AuditLog
from tests.conftest import FakeMailer, criar_usuario, entrar

NOVO = {"email": "bruno@exemplo.com", "full_name": "Bruno Lima", "role": "agent"}


def _admin(client: TestClient, db: Session) -> None:
    criar_usuario(db, "admin@exemplo.com", "admin", nome="Admin")
    entrar(client, "admin@exemplo.com")


def test_so_admin_administra_usuarios(client: TestClient, db: Session) -> None:
    criar_usuario(db, grupos={"TI": "supervisor"})
    entrar(client)
    assert client.get("/api/v1/users").status_code == 403
    assert client.post("/api/v1/users", json=NOVO).status_code == 403


def test_criar_usuario_sem_smtp_devolve_o_link(
    client: TestClient, db: Session, mailer: FakeMailer
) -> None:
    _admin(client, db)
    r = client.post("/api/v1/users", json=NOVO)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "convite_pendente"
    assert body["link"]["purpose"] == "invite"
    assert body["link"]["sent_by_email"] is False
    assert body["link"]["url"].startswith("http://teste/convite/")
    assert mailer.sent[-1][0] == "bruno@exemplo.com"
    acoes = set(db.scalars(select(AuditLog.action)))
    assert {"user.created", "user.invite_sent"} <= acoes


def test_criar_usuario_com_smtp_nao_expoe_o_link(
    client: TestClient, db: Session, mailer: FakeMailer
) -> None:
    mailer.configured = True
    _admin(client, db)
    link = client.post("/api/v1/users", json=NOVO).json()["link"]
    assert link == {"purpose": "invite", "sent_by_email": True, "url": None}


def test_email_duplicado(client: TestClient, db: Session) -> None:
    _admin(client, db)
    client.post("/api/v1/users", json=NOVO)
    r = client.post("/api/v1/users", json={**NOVO, "email": "BRUNO@exemplo.com"})
    assert r.status_code == 409


def test_editar_e_desativar_encerra_sessoes(client: TestClient, db: Session) -> None:
    _admin(client, db)
    ana = criar_usuario(db)
    with TestClient(client.app) as sessao_ana:
        entrar(sessao_ana)
        r = client.patch(
            f"/api/v1/users/{ana.public_id}", json={"role": "auditor", "full_name": "Ana S."}
        )
        assert r.json()["role"] == "auditor" and r.json()["full_name"] == "Ana S."
        # Papel novo vale na hora, sem precisar entrar de novo
        assert "audit.view" in sessao_ana.get("/api/v1/me").json()["permissions"]
        r = client.patch(f"/api/v1/users/{ana.public_id}", json={"is_active": False})
        assert r.json()["status"] == "inativo"
        assert sessao_ana.get("/api/v1/me").status_code == 401


def test_nao_remove_o_ultimo_admin(client: TestClient, db: Session) -> None:
    _admin(client, db)
    admin_id = client.get("/api/v1/me").json()["id"]
    r = client.patch(f"/api/v1/users/{admin_id}", json={"role": "agent"})
    assert r.status_code == 409
    r = client.patch(f"/api/v1/users/{admin_id}", json={"is_active": False})
    assert r.status_code == 409


def test_link_de_acesso_reenvia_convite_ou_redefinicao(client: TestClient, db: Session) -> None:
    _admin(client, db)
    ana = criar_usuario(db)
    convidado = client.post("/api/v1/users", json=NOVO).json()
    assert client.post(f"/api/v1/users/{convidado['id']}/link").json()["purpose"] == "invite"
    r = client.post(f"/api/v1/users/{ana.public_id}/link").json()
    assert r["purpose"] == "password_reset"
    assert r["url"].startswith("http://teste/redefinir-senha/")


def test_lista_mostra_grupos(client: TestClient, db: Session) -> None:
    _admin(client, db)
    criar_usuario(db, grupos={"TI – Suporte": "member"})
    itens = client.get("/api/v1/users").json()["items"]
    ana = next(u for u in itens if u["email"] == "ana@exemplo.com")
    assert ana["teams"] == [{"id": ana["teams"][0]["id"], "name": "TI – Suporte", "role": "member"}]
