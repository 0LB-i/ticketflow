"""Administração de usuários (docs/13: /admin/usuarios)."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from chamados.modules.audit.models import AuditLog
from chamados.modules.identity.models import User
from tests.conftest import SENHA, criar_usuario, entrar, grupo

NOVO = {
    "email": "bruno@exemplo.com",
    "username": "bruno",
    "full_name": "Bruno Lima",
    "display_name": "Bruno",
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
    with TestClient(client.app) as sessao_bruno:
        entrar(sessao_bruno, "Bruno", "Provisoria#2026")  # pelo usuário, sem diferença de caixa
    acoes = set(db.scalars(select(AuditLog.action)))
    assert "user.created" in acoes


def test_nome_de_exibicao_e_o_que_aparece_no_sistema(client: TestClient, db: Session) -> None:
    _admin(client, db)
    ti = grupo(db, "TI")
    r = client.post("/api/v1/users", json={**NOVO, "team_ids": [str(ti.public_id)]})
    assert (r.json()["full_name"], r.json()["display_name"]) == ("Bruno Lima", "Bruno")
    membros = client.get("/api/v1/teams").json()["items"][0]["members"]
    assert [m["display_name"] for m in membros] == ["Bruno"]
    with TestClient(client.app) as sessao_bruno:
        entrar(sessao_bruno, "bruno", "Provisoria#2026")
        assert sessao_bruno.get("/api/v1/me").json()["display_name"] == "Bruno"
    r = client.patch(f"/api/v1/users/{r.json()['id']}", json={"display_name": " Bruninho "})
    assert (r.json()["full_name"], r.json()["display_name"]) == ("Bruno Lima", "Bruninho")


def test_nome_so_com_espacos_e_recusado(client: TestClient, db: Session) -> None:
    """O mínimo de 2 caracteres vale sem os espaços: um nome vazio quebraria os e-mails."""
    _admin(client, db)
    for campo in ("full_name", "display_name"):
        r = client.post("/api/v1/users", json={**NOVO, campo: "   "})
        assert r.status_code == 422, campo
    r = client.post("/api/v1/users", json=NOVO)
    r = client.patch(f"/api/v1/users/{r.json()['id']}", json={"display_name": " x "})
    assert r.status_code == 422


def test_nome_de_usuario_valido_e_unico(client: TestClient, db: Session) -> None:
    _admin(client, db)
    for errado in ("joão", "b", "bruno@x", "com espaço", ".bruno"):
        r = client.post("/api/v1/users", json={**NOVO, "username": errado})
        assert r.status_code == 422, errado
    r = client.post("/api/v1/users", json={**NOVO, "username": " Bruno.Lima "})
    assert r.status_code == 201 and r.json()["username"] == "bruno.lima"
    r = client.post(
        "/api/v1/users", json={**NOVO, "email": "outro@x.com", "username": "BRUNO.lima"}
    )
    assert r.status_code == 409


def test_editar_nome_de_usuario(client: TestClient, db: Session) -> None:
    _admin(client, db)
    ana = criar_usuario(db)
    criar_usuario(db, "bia@exemplo.com", username="bia")
    url = f"/api/v1/users/{ana.public_id}"
    assert client.patch(url, json={"username": "bia"}).status_code == 409
    assert client.patch(url, json={"username": "ana.souza"}).json()["username"] == "ana.souza"
    with TestClient(client.app) as sessao_ana:
        entrar(sessao_ana, "ana.souza")


def test_senha_inicial_fraca_e_recusada(client: TestClient, db: Session) -> None:
    _admin(client, db)
    for senha in ("curta", "12345678", "bruno@exemplo.com", "bruno"):
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


def test_excluir_tira_do_sistema_e_libera_o_email(client: TestClient, db: Session) -> None:
    _admin(client, db)
    ana = criar_usuario(db, grupos={"TI": "supervisor"})
    with TestClient(client.app) as sessao_ana:
        entrar(sessao_ana)
        assert client.delete(f"/api/v1/users/{ana.public_id}").status_code == 204
        assert sessao_ana.get("/api/v1/me").status_code == 401
    r = client.post("/api/v1/auth/login", json={"login": "ana@exemplo.com", "password": SENHA})
    assert r.status_code == 401
    assert client.get(f"/api/v1/users/{ana.public_id}").status_code == 404
    assert client.delete(f"/api/v1/users/{ana.public_id}").status_code == 404
    emails = [u["email"] for u in client.get("/api/v1/users").json()["items"]]
    assert emails == ["admin@exemplo.com"]
    ti = client.get("/api/v1/teams").json()["items"][0]
    assert ti["members"] == []
    db.expire_all()
    excluida = db.get(User, ana.id)
    assert excluida is not None and excluida.full_name == "Ana Souza"  # fica para o histórico
    antes = db.scalar(select(AuditLog.before).where(AuditLog.action == "user.deleted"))
    assert antes is not None and antes["email"] == "ana@exemplo.com"
    assert antes["teams"] == ["TI"]
    r = client.post("/api/v1/users", json={**NOVO, "email": "ana@exemplo.com"})
    assert r.status_code == 201


def test_nao_exclui_o_proprio_usuario(client: TestClient, db: Session) -> None:
    _admin(client, db)
    admin_id = client.get("/api/v1/me").json()["id"]
    assert client.delete(f"/api/v1/users/{admin_id}").status_code == 409


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
