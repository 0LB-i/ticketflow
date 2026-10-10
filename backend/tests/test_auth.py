"""Login, sessão, CSRF e força bruta (docs/09 §9.3 e §9.7)."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from chamados.modules.audit.models import AuditLog
from chamados.modules.identity.models import User, UserSession
from chamados.modules.identity.sessions import now
from tests.conftest import SENHA, FakeMailer, criar_usuario, entrar

LOGIN = "/api/v1/auth/login"


def test_login_cria_sessao_e_me_traz_papel_grupos_e_permissoes(
    client: TestClient, db: Session
) -> None:
    criar_usuario(db, grupos={"TI – Suporte": "supervisor"})
    r = client.post(LOGIN, json={"login": "ANA@exemplo.com", "password": SENHA})
    assert r.status_code == 204
    cookie_sessao = next(c for c in r.headers.get_list("set-cookie") if c.startswith("tf_sessao="))
    assert "HttpOnly" in cookie_sessao and "SameSite=lax" in cookie_sessao

    me = client.get("/api/v1/me").json()
    assert me["email"] == "ana@exemplo.com"
    assert me["role"] == "agent"
    assert me["teams"][0]["name"] == "TI – Suporte" and me["teams"][0]["role"] == "supervisor"
    assert "ticket.approve" in me["permissions"]
    assert "admin.users" not in me["permissions"]
    assert db.scalar(select(AuditLog.action).where(AuditLog.action == "auth.login"))


def test_cookie_secure_em_producao(client: TestClient, db: Session) -> None:
    client.app.state.settings.cookie_secure = True  # type: ignore[attr-defined]
    criar_usuario(db)
    r = client.post(LOGIN, json={"login": "ana@exemplo.com", "password": SENHA})
    assert all("Secure" in c for c in r.headers.get_list("set-cookie"))


def test_mensagem_generica_nao_revela_se_o_email_existe(client: TestClient, db: Session) -> None:
    criar_usuario(db)
    senha_errada = client.post(LOGIN, json={"login": "ana@exemplo.com", "password": "x" * 12})
    sem_conta = client.post(LOGIN, json={"login": "ninguem@exemplo.com", "password": "x" * 12})
    assert senha_errada.status_code == sem_conta.status_code == 401
    assert senha_errada.json() == sem_conta.json()
    assert senha_errada.json()["detail"] == "E-mail ou senha inválidos."


def test_usuario_inativo_ou_sem_senha_nao_entra(client: TestClient, db: Session) -> None:
    criar_usuario(db, "inativo@exemplo.com", ativo=False)
    criar_usuario(db, "convidado@exemplo.com", senha=None)
    for email in ("inativo@exemplo.com", "convidado@exemplo.com"):
        assert client.post(LOGIN, json={"login": email, "password": SENHA}).status_code == 401


def test_sem_sessao_da_401(client: TestClient) -> None:
    r = client.get("/api/v1/me")
    assert r.status_code == 401
    assert r.headers["content-type"] == "application/problem+json"


def test_csrf_obrigatorio_e_logout(client: TestClient, db: Session) -> None:
    criar_usuario(db)
    entrar(client)
    csrf = client.headers.pop("X-CSRF-Token")
    assert client.post("/api/v1/auth/logout").status_code == 403
    assert client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "errado"}).status_code == 403
    assert client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
    assert client.get("/api/v1/me").status_code == 401


def test_sessao_expira_sem_uso(client: TestClient, db: Session) -> None:
    criar_usuario(db)
    entrar(client)
    db.execute(update(UserSession).values(last_seen_at=now() - timedelta(hours=9)))
    db.commit()
    assert client.get("/api/v1/me").status_code == 401


def test_sessao_expira_no_prazo_maximo(client: TestClient, db: Session) -> None:
    criar_usuario(db)
    entrar(client)
    db.execute(update(UserSession).values(expires_at=now() - timedelta(seconds=1)))
    db.commit()
    assert client.get("/api/v1/me").status_code == 401


def test_bloqueio_apos_10_falhas_avisa_o_dono(
    client: TestClient, db: Session, mailer: FakeMailer
) -> None:
    user = criar_usuario(db)
    db.execute(
        update(User).values(failed_logins=9, last_failed_login_at=now() - timedelta(hours=1))
    )
    db.commit()
    assert client.post(LOGIN, json={"login": user.email, "password": "x" * 12}).status_code == 401
    db.refresh(user)
    assert user.locked_until is not None
    assert "bloqueada" in mailer.sent[-1][1]
    # Bloqueada, nem a senha certa entra
    assert client.post(LOGIN, json={"login": user.email, "password": SENHA}).status_code == 401


def test_espera_progressiva_apos_5_falhas(client: TestClient, db: Session) -> None:
    user = criar_usuario(db)
    db.execute(update(User).values(failed_logins=5, last_failed_login_at=now()))
    db.commit()
    # Dentro da espera, a tentativa é recusada sem conferir a senha
    assert client.post(LOGIN, json={"login": user.email, "password": SENHA}).status_code == 401
    db.execute(update(User).values(last_failed_login_at=now() - timedelta(minutes=2)))
    db.commit()
    assert client.post(LOGIN, json={"login": user.email, "password": SENHA}).status_code == 204
    db.refresh(user)
    assert user.failed_logins == 0


def test_limite_por_ip(client: TestClient, db: Session) -> None:
    for _ in range(20):
        client.post(LOGIN, json={"login": "ninguem@exemplo.com", "password": "x" * 12})
    r = client.post(LOGIN, json={"login": "ninguem@exemplo.com", "password": "x" * 12})
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0


def test_troca_de_senha_mantem_so_a_sessao_atual(client: TestClient, db: Session) -> None:
    criar_usuario(db)
    entrar(client)
    with TestClient(client.app) as outro:
        entrar(outro)
        r = client.post(
            "/api/v1/me/password",
            json={"current_password": "errada errada", "new_password": "nova senha bem longa"},
        )
        assert r.status_code == 422
        r = client.post(
            "/api/v1/me/password",
            json={"current_password": SENHA, "new_password": "nova senha bem longa"},
        )
        assert r.status_code == 204
        assert client.get("/api/v1/me").status_code == 200
        assert outro.get("/api/v1/me").status_code == 401
