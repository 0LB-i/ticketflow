"""Administrador padrão admin/admin com troca obrigatória de senha (docs/09 §9.2)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import criar_usuario, entrar


def test_primeiro_acesso_obriga_a_trocar_a_senha(client: TestClient, db: Session) -> None:
    criar_usuario(
        db, None, "admin", nome="Administrador", username="admin", senha="admin", trocar_senha=True
    )
    entrar(client, "ADMIN", "admin")  # usuário sem diferenciar maiúsculas
    me = client.get("/api/v1/me").json()
    assert me["must_change_password"] is True and me["username"] == "admin"

    # Antes da troca, nada além de /me, trocar a senha e sair
    r = client.get("/api/v1/users")
    assert r.status_code == 403
    assert r.json()["detail"] == "Troque a senha provisória antes de continuar."

    # Senha curta ou igual à atual não serve; a atual não é pedida
    curta = client.post("/api/v1/me/password", json={"new_password": "admin12"})
    assert curta.status_code == 422
    assert client.post("/api/v1/me/password", json={"new_password": "Gato2026"}).status_code == 204

    assert client.get("/api/v1/me").json()["must_change_password"] is False
    assert client.get("/api/v1/users").status_code == 200
    client.cookies.clear()
    entrar(client, "admin", "Gato2026")


def test_troca_comum_continua_pedindo_a_senha_atual(client: TestClient, db: Session) -> None:
    criar_usuario(db)
    entrar(client)
    r = client.post("/api/v1/me/password", json={"new_password": "outra senha boa"})
    assert r.status_code == 422
    assert r.json()["detail"] == "A senha atual não confere."


def test_admin_cadastra_email_do_admin_padrao(client: TestClient, db: Session) -> None:
    padrao = criar_usuario(db, None, "admin", nome="Administrador", username="admin")
    criar_usuario(db, "chefe@exemplo.com", "admin", nome="Chefe")
    entrar(client, "chefe@exemplo.com")
    # Sem e-mail e sem SMTP: o link aparece na tela; com SMTP, é preciso cadastrar o e-mail
    assert client.post(f"/api/v1/users/{padrao.public_id}/link").json()["url"]
    client.app.state.mailer.configured = True  # type: ignore[attr-defined]
    assert client.post(f"/api/v1/users/{padrao.public_id}/link").status_code == 409

    r = client.patch(f"/api/v1/users/{padrao.public_id}", json={"email": "ti@exemplo.com"})
    assert r.json()["email"] == "ti@exemplo.com" and r.json()["username"] == "admin"
    r = client.patch(f"/api/v1/users/{padrao.public_id}", json={"email": "chefe@exemplo.com"})
    assert r.status_code == 409
