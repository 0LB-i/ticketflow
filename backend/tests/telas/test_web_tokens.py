"""Meus tokens de API: a tela (web/tokens.py) e as rotas /me/tokens da API."""

import re

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from chamados.modules.audit.models import AuditLog
from chamados.modules.identity.models import ApiToken
from tests.apoio import com_token, criar_token
from tests.conftest import criar_usuario, entrar, outra_sessao

TOKEN = re.compile(r'id="token-valor"[^>]*value="(tf_[^"]+)"')


def _criar(client: TestClient, **dados: str) -> tuple[int, str]:
    r = client.post(
        "/meus-tokens",
        data={"csrf_token": client.cookies["tf_csrf"], "escopo": "read", "dias": "90", **dados},
    )
    return r.status_code, r.text


def test_criar_mostra_o_valor_uma_vez_e_ele_funciona(client: TestClient, db: Session) -> None:
    criar_usuario(db, "ana@x.com")
    entrar(client, "ana@x.com")
    assert "/meus-tokens" in client.get("/chamados").text  # no menu do usuário
    r = client.get("/meus-tokens")
    assert r.status_code == 200
    assert "Você ainda não tem tokens." in r.text
    assert "claude mcp add --transport http ticketflow http://teste/mcp" in r.text

    status, texto = _criar(client, nome="Claude Code", escopo="write", dias="30")
    assert status == 201
    valor = TOKEN.search(texto)
    assert valor is not None
    assert "Copie o valor agora" in texto
    assert "Leitura e escrita" in texto

    # Na próxima visita, o valor não aparece mais; o token, sim
    r = client.get("/meus-tokens")
    assert valor.group(1) not in r.text
    assert "Claude Code" in r.text and "Nunca usado" in r.text

    pela_api = outra_sessao(client)
    me = pela_api.get("/api/v1/me", headers={"Authorization": f"Bearer {valor.group(1)}"})
    assert me.status_code == 200
    token = db.scalar(select(ApiToken))
    assert token is not None and token.scope == "write" and token.expires_at is not None
    log = db.scalar(select(AuditLog).where(AuditLog.action == "api_token.created"))
    assert log is not None and log.actor_user_id is not None


def test_criar_sem_nome_volta_com_o_erro(client: TestClient, db: Session) -> None:
    criar_usuario(db, "ana@x.com")
    entrar(client, "ana@x.com")
    status, texto = _criar(client, nome="   ")
    assert status == 422
    assert "Dê um nome ao token." in texto
    assert db.scalar(select(ApiToken)) is None


def test_revogar(client: TestClient, db: Session) -> None:
    criar_usuario(db, "ana@x.com")
    raw = criar_token(db, "ana@x.com")
    token = db.scalar(select(ApiToken))
    assert token is not None
    entrar(client, "ana@x.com")
    r = client.post(
        f"/meus-tokens/{token.public_id}/revogar",
        data={"csrf_token": client.cookies["tf_csrf"]},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "Você ainda não tem tokens." in client.get("/meus-tokens").text
    pela_api = outra_sessao(client)
    assert pela_api.get("/api/v1/me", headers={"Authorization": f"Bearer {raw}"}).status_code == 401


def test_so_os_proprios_tokens(client: TestClient, db: Session) -> None:
    criar_usuario(db, "ana@x.com")
    criar_usuario(db, "bia@x.com", nome="Bia")
    criar_token(db, "bia@x.com")
    da_bia = db.scalar(select(ApiToken))
    assert da_bia is not None
    entrar(client, "ana@x.com")
    assert client.get("/api/v1/me/tokens").json() == {"items": []}
    assert client.delete(f"/api/v1/me/tokens/{da_bia.public_id}").status_code == 404
    r = client.post(
        f"/meus-tokens/{da_bia.public_id}/revogar",
        data={"csrf_token": client.cookies["tf_csrf"]},
        follow_redirects=False,
    )
    assert r.status_code == 303
    db.refresh(da_bia)
    assert da_bia.revoked_at is None


def test_um_token_nao_gerencia_tokens(client: TestClient, db: Session) -> None:
    criar_usuario(db, "ana@x.com")
    com_token(client, criar_token(db, "ana@x.com"))
    assert client.get("/api/v1/me/tokens").status_code == 403
    r = client.post("/api/v1/me/tokens", json={"name": "Outro", "scope": "write"})
    assert r.status_code == 403
    assert r.json()["detail"] == "Esta ação só pode ser feita pela interface."


def test_api_cria_lista_e_revoga(client: TestClient, db: Session) -> None:
    criar_usuario(db, "ana@x.com")
    entrar(client, "ana@x.com")
    r = client.post("/api/v1/me/tokens", json={"name": " Script ", "days": 365})
    assert r.status_code == 201, r.text
    criado = r.json()
    assert criado["name"] == "Script" and criado["scope"] == "read"
    assert criado["token"].startswith("tf_")
    itens = client.get("/api/v1/me/tokens").json()["items"]
    assert [i["id"] for i in itens] == [criado["id"]]
    assert "token" not in itens[0]
    assert client.post("/api/v1/me/tokens", json={"name": "x", "days": 400}).status_code == 422
    assert client.delete(f"/api/v1/me/tokens/{criado['id']}").status_code == 204
    assert client.get("/api/v1/me/tokens").json() == {"items": []}
