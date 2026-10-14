"""Administração de usuários (docs/13: /admin/usuarios)."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from chamados.modules.audit.models import AuditLog
from chamados.modules.identity.models import User
from tests.conftest import criar_usuario, entrar, grupo

NOVO = {
    "email": "bruno@exemplo.com",
    "full_name": "Bruno Lima",
    "role": "agent",
    "password": "Provisoria#2026",
}


def _admin(client: TestClient, db: Session) -> None:
    criar_usuario(db, "admin@exemplo.com", "admin", nome="Admin")
    entrar(client, "admin@exemplo.com")


def test_so_admin_administra_usuarios(client: TestClient, db: Session) -> None:
    criar_usuario(db, grupos={"TI": "supervisor"})
    entrar(client)
    assert client.get("/api/v1/users").status_code == 403
    assert client.post("/api/v1/users", json=NOVO).status_code == 403


def test_criar_usuario_com_senha_inicial_e_troca_no_primeiro_acesso(
    client: TestClient, db: Session
) -> None:
    _admin(client, db)
    r = client.post("/api/v1/users", json=NOVO)
    assert r.status_code == 201
    assert r.json()["status"] == "ativo"
    with TestClient(client.app) as sessao_bruno:
        entrar(sessao_bruno, "bruno@exemplo.com", "Provisoria#2026")
        assert sessao_bruno.get("/api/v1/me").json()["must_change_password"] is True
    acoes = set(db.scalars(select(AuditLog.action)))
    assert "user.created" in acoes


def test_senha_inicial_fraca_e_recusada(client: TestClient, db: Session) -> None:
    _admin(client, db)
    for senha in ("curta", "12345678", "bruno@exemplo.com"):
        r = client.post("/api/v1/users", json={**NOVO, "password": senha})
        assert r.status_code == 422, senha
    assert db.scalar(select(User.id).where(User.email == "bruno@exemplo.com")) is None


def test_criar_usuario_ja_como_membro_dos_grupos(client: TestClient, db: Session) -> None:
    _admin(client, db)
    ti, rh = grupo(db, "TI"), grupo(db, "RH")
    r = client.post(
        "/api/v1/users", json={**NOVO, "team_ids": [str(ti.public_id), str(rh.public_id)]}
    )
    assert r.status_code == 201
    assert [(g["name"], g["role"]) for g in r.json()["teams"]] == [
        ("RH", "member"),
        ("TI", "member"),
    ]
    acoes = list(db.scalars(select(AuditLog.action).where(AuditLog.target_type == "team")))
    assert acoes == ["team.member_set", "team.member_set"]


def test_criar_usuario_em_grupo_inativo_e_recusado(client: TestClient, db: Session) -> None:
    _admin(client, db)
    ti = grupo(db, "TI")
    ti.is_active = False
    db.commit()
    r = client.post("/api/v1/users", json={**NOVO, "team_ids": [str(ti.public_id)]})
    assert r.status_code == 422
    assert db.scalar(select(User.id).where(User.email == "bruno@exemplo.com")) is None


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
    convidado = criar_usuario(db, "bruno@exemplo.com", nome="Bruno Lima", senha=None)
    assert client.post(f"/api/v1/users/{convidado.public_id}/link").json()["purpose"] == "invite"
    r = client.post(f"/api/v1/users/{ana.public_id}/link").json()
    assert r["purpose"] == "password_reset"
    assert r["url"].startswith("http://teste/redefinir-senha/")


def test_lista_mostra_grupos(client: TestClient, db: Session) -> None:
    _admin(client, db)
    criar_usuario(db, grupos={"TI – Suporte": "member"})
    itens = client.get("/api/v1/users").json()["items"]
    ana = next(u for u in itens if u["email"] == "ana@exemplo.com")
    assert ana["teams"] == [{"id": ana["teams"][0]["id"], "name": "TI – Suporte", "role": "member"}]
