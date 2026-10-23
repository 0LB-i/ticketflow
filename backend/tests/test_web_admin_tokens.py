"""Administração dos tokens de API: a tela /admin/tokens e as rotas /admin/api-tokens."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from chamados.modules.audit.models import AuditLog
from chamados.modules.identity.models import ApiToken, User
from tests.conftest import criar_usuario, entrar
from tests.test_tokens_api import com_token, criar_token


def _token_de(db: Session, email: str) -> ApiToken:
    token = db.scalar(select(ApiToken).join(ApiToken.user).where(User.email == email))
    assert token is not None
    return token


def test_admin_ve_os_tokens_de_todos_e_filtra(client: TestClient, db: Session) -> None:
    criar_usuario(db, "adm@x.com", "admin", nome="Adm")
    criar_usuario(db, "ana@x.com", nome="Ana")
    criar_usuario(db, "bia@x.com", nome="Bia", ativo=False)
    criar_token(db, "ana@x.com")
    criar_token(db, "bia@x.com", "read")
    entrar(client, "adm@x.com")

    r = client.get("/admin/tokens")
    assert r.status_code == 200
    assert 'href="/admin/tokens"' in r.text  # no menu da administração
    assert "ana@x.com" in r.text and "bia@x.com" in r.text
    assert "Leitura e escrita" in r.text and "Só leitura" in r.text

    ana = str(_token_de(db, "ana@x.com").user.public_id)
    r = client.get(f"/admin/tokens?pessoa={ana}")
    assert "ana@x.com" in r.text and "bia@x.com" not in r.text
    # Um filtro inválido mostra todos
    assert "bia@x.com" in client.get("/admin/tokens?pessoa=x").text

    itens = client.get("/api/v1/admin/api-tokens").json()["items"]
    assert [(i["user"]["display_name"], i["user"]["is_active"]) for i in itens] == [
        ("Ana", True),
        ("Bia", False),
    ]


def test_admin_revoga_o_token_de_outra_pessoa(client: TestClient, db: Session) -> None:
    criar_usuario(db, "adm@x.com", "admin", nome="Adm")
    criar_usuario(db, "ana@x.com", nome="Ana")
    raw = criar_token(db, "ana@x.com")
    token = _token_de(db, "ana@x.com")
    entrar(client, "adm@x.com")

    volta = f"/admin/tokens?pessoa={token.user.public_id}"
    r = client.post(
        f"/admin/tokens/{token.public_id}/revogar",
        data={"csrf_token": client.cookies["tf_csrf"], "volta": volta},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == volta
    assert "Nenhum token ativo." in client.get("/admin/tokens").text
    pela_api = TestClient(client.app)
    assert pela_api.get("/api/v1/me", headers={"Authorization": f"Bearer {raw}"}).status_code == 401
    log = db.scalar(select(AuditLog).where(AuditLog.action == "api_token.revoked"))
    assert log is not None
    adm = db.scalar(select(User.id).where(User.email == "adm@x.com"))
    assert log.actor_user_id == adm
    # De novo: o token já foi revogado
    assert client.delete(f"/api/v1/admin/api-tokens/{token.public_id}").status_code == 404


def test_so_quem_administra_os_usuarios(client: TestClient, db: Session) -> None:
    criar_usuario(db, "ana@x.com", nome="Ana")
    criar_token(db, "ana@x.com")
    token = _token_de(db, "ana@x.com")
    entrar(client, "ana@x.com")
    assert 'href="/admin/tokens"' not in client.get("/chamados").text
    assert client.get("/admin/tokens").status_code == 403
    assert client.get("/api/v1/admin/api-tokens").status_code == 403
    r = client.post(
        f"/admin/tokens/{token.public_id}/revogar",
        data={"csrf_token": client.cookies["tf_csrf"]},
        follow_redirects=False,
    )
    assert r.status_code == 403
    db.refresh(token)
    assert token.revoked_at is None


def test_token_de_admin_nao_administra_tokens(client: TestClient, db: Session) -> None:
    criar_usuario(db, "adm@x.com", "admin")
    com_token(client, criar_token(db, "adm@x.com"))
    r = client.get("/api/v1/admin/api-tokens")
    assert r.status_code == 403
    assert r.json()["detail"] == "Tokens de API não acessam a administração."
