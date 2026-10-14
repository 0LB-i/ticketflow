"""Convite, esqueci a senha e regras de senha (docs/09 §9.3 e §9.4)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from chamados.modules.identity.passwords import password_problem
from tests.conftest import SENHA, FakeMailer, criar_usuario, entrar


def _token(url: str) -> str:
    return url.rsplit("/", 1)[1]


def test_regras_de_senha() -> None:
    assert password_problem("curta12", "a@b.com") is not None  # menos de 8
    assert password_problem("password1234", "a@b.com") is not None  # lista de comuns
    assert password_problem("12345678", "a@b.com") is not None
    assert password_problem("aaaaaaaa", "a@b.com") is not None  # poucos caracteres distintos
    assert password_problem("joao.silva.ti", "joao.silva.ti@b.com") is not None
    assert password_problem("Admin", None, "admin") is not None  # igual ao usuário
    assert password_problem("Gato2026", "a@b.com") is None  # 8 caracteres bastam
    assert password_problem("cavalo bateria grampo", "a@b.com") is None


def test_esqueci_a_senha_responde_igual_exista_ou_nao(
    client: TestClient, db: Session, mailer: FakeMailer
) -> None:
    criar_usuario(db)
    r1 = client.post("/api/v1/auth/password/forgot", json={"email": "ninguem@exemplo.com"})
    r2 = client.post("/api/v1/auth/password/forgot", json={"email": "ana@exemplo.com"})
    assert r1.status_code == r2.status_code == 202
    assert len(mailer.sent) == 1
    assert mailer.last_link().startswith("http://teste/redefinir-senha/")


def test_redefinir_senha_encerra_sessoes_e_token_e_de_uso_unico(
    client: TestClient, db: Session, mailer: FakeMailer
) -> None:
    criar_usuario(db)
    entrar(client)
    client.post("/api/v1/auth/password/forgot", json={"email": "ana@exemplo.com"})
    token = _token(mailer.last_link())

    info = client.get(f"/api/v1/auth/tokens/{token}").json()
    assert info == {
        "purpose": "password_reset",
        "email": "ana@exemplo.com",
        "full_name": "Ana Souza",
    }

    fraca = client.post("/api/v1/auth/password/reset", json={"token": token, "password": "curta"})
    assert fraca.status_code == 422
    nova = {"token": token, "password": "nova senha bem longa"}
    assert client.post("/api/v1/auth/password/reset", json=nova).status_code == 204
    assert client.get("/api/v1/me").status_code == 401  # sessões antigas encerradas
    assert client.post("/api/v1/auth/password/reset", json=nova).status_code == 404
    assert client.get(f"/api/v1/auth/tokens/{token}").status_code == 404
    entrar(client, senha="nova senha bem longa")


def test_token_de_convite_nao_serve_para_redefinir(
    client: TestClient, db: Session, mailer: FakeMailer
) -> None:
    criar_usuario(db, "admin@exemplo.com", "admin")
    entrar(client, "admin@exemplo.com")
    bruno = criar_usuario(db, "bruno@exemplo.com", nome="Bruno Lima", senha=None)
    r = client.post(f"/api/v1/users/{bruno.public_id}/link")
    token = _token(r.json()["url"])
    body = {"token": token, "password": "senha do bruno longa"}
    assert client.post("/api/v1/auth/password/reset", json=body).status_code == 404
    assert client.post("/api/v1/auth/invite/accept", json=body).status_code == 204
    client.cookies.clear()
    entrar(client, "bruno@exemplo.com", "senha do bruno longa")


def test_novo_link_invalida_o_anterior(client: TestClient, db: Session, mailer: FakeMailer) -> None:
    criar_usuario(db)
    client.post("/api/v1/auth/password/forgot", json={"email": "ana@exemplo.com"})
    primeiro = _token(mailer.last_link())
    client.post("/api/v1/auth/password/forgot", json={"email": "ana@exemplo.com"})
    assert client.get(f"/api/v1/auth/tokens/{primeiro}").status_code == 404
    assert client.get(f"/api/v1/auth/tokens/{_token(mailer.last_link())}").status_code == 200


def test_senha_atual_continua_valendo_ate_redefinir(client: TestClient, db: Session) -> None:
    criar_usuario(db)
    client.post("/api/v1/auth/password/forgot", json={"email": "ana@exemplo.com"})
    entrar(client, senha=SENHA)
