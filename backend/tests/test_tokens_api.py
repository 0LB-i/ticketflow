"""Tokens de API (docs/05): `Authorization: Bearer`, em nome de um usuário, com as permissões
dele; `read` só lê; a administração fica de fora."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from chamados import cli
from chamados.config import get_settings
from chamados.modules.audit.models import AuditLog
from chamados.modules.identity.models import ApiToken, User
from chamados.modules.identity.tokens import new_api_token
from chamados.modules.jobs.models import OutboxEvent
from chamados.modules.tickets.models import Ticket
from tests.conftest import criar_usuario, entrar
from tests.test_chamados import API, cenario, eventos, registrar  # noqa: F401


def criar_token(
    db: Session, email: str, scope: str = "write", expires_at: datetime | None = None
) -> str:
    user = db.scalar(select(User).where(User.email == email))
    assert user is not None
    raw, token = new_api_token(user, "Teste", scope, expires_at)
    db.add(token)
    db.commit()
    return raw


def com_token(client: TestClient, raw: str) -> TestClient:
    """Só o token: sem o cookie da sessão nem o header CSRF."""
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    client.headers["Authorization"] = f"Bearer {raw}"
    return client


def test_token_de_escrita_age_como_o_usuario_sem_csrf(
    client: TestClient,
    cenario: dict[str, Any],  # noqa: F811
    db: Session,
) -> None:
    com_token(client, criar_token(db, "ana@x.com"))
    t = registrar(client, cenario)
    assert t["created_by"]["display_name"] == "Ana"
    r = client.post(f"{API}/{t['number']}/comments", json={"body": "Pelo token"})
    assert r.status_code == 201, r.text
    assert client.get("/api/v1/me").json()["display_name"] == "Ana"
    usado = db.scalar(select(ApiToken.last_used_at))
    assert usado is not None


def test_o_que_o_token_faz_fica_marcado_como_api(
    client: TestClient,
    cenario: dict[str, Any],  # noqa: F811
    db: Session,
) -> None:
    pela_tela = registrar(client, cenario)["number"]
    com_token(client, criar_token(db, "ana@x.com"))
    pelo_token = registrar(client, cenario)["number"]
    assert client.post(f"{API}/{pela_tela}/comments", json={"body": "Oi"}).status_code == 201

    assert "via" not in eventos(client, pela_tela)[0]["payload"]
    criado = eventos(client, pelo_token)[0]
    assert criado["type"] == "ticket.created"
    assert criado["actor"]["display_name"] == "Ana"
    assert criado["payload"]["via"] == "api"
    outbox = {
        (e.event_type, e.payload["ticket_id"]): e.payload
        for e in db.scalars(select(OutboxEvent).order_by(OutboxEvent.id))
    }
    ids = {
        t: db.scalar(select(Ticket.id).where(Ticket.number == t)) for t in (pela_tela, pelo_token)
    }
    assert "via" not in outbox[("ticket.created", ids[pela_tela])]
    assert outbox[("ticket.created", ids[pelo_token])]["via"] == "api"
    assert outbox[("comment.created", ids[pela_tela])]["via"] == "api"


def test_token_de_leitura_so_le(
    client: TestClient,
    cenario: dict[str, Any],  # noqa: F811
    db: Session,
) -> None:
    numero = registrar(client, cenario)["number"]
    com_token(client, criar_token(db, "ana@x.com", "read"))
    assert client.get(f"{API}/{numero}").status_code == 200
    assert [t["number"] for t in client.get(API).json()["items"]] == [numero]
    r = client.post(f"{API}/{numero}/comments", json={"body": "Não pode"})
    assert r.status_code == 403
    assert r.json()["detail"] == "Este token de API só permite leitura."


def test_token_segue_a_visibilidade(
    client: TestClient,
    cenario: dict[str, Any],  # noqa: F811
    db: Session,
) -> None:
    numero = registrar(client, cenario)["number"]  # do TI
    com_token(client, criar_token(db, "caio@x.com"))  # da Infra
    assert client.get(f"{API}/{numero}").status_code == 403


@pytest.mark.parametrize("caso", ["errado", "revogado", "expirado", "inativo", "esquema"])
def test_token_recusado(client: TestClient, db: Session, caso: str) -> None:
    user = criar_usuario(db, "ana@x.com")
    raw = criar_token(db, "ana@x.com")
    token = db.scalar(select(ApiToken))
    assert token is not None
    header = f"Bearer {raw}"
    match caso:
        case "errado":
            header = "Bearer tf_outro"
        case "revogado":
            token.revoked_at = datetime.now(UTC)
        case "expirado":
            token.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        case "inativo":
            user.is_active = False
        case "esquema":
            header = f"Basic {raw}"
    db.commit()
    r = client.get("/api/v1/me", headers={"Authorization": header})
    assert r.status_code == 401
    assert r.json()["detail"] == "Token de API inválido, expirado ou revogado."


def test_token_nao_entra_na_administracao(client: TestClient, db: Session) -> None:
    criar_usuario(db, "adm@x.com", "admin")
    com_token(client, criar_token(db, "adm@x.com"))
    for url in ("/api/v1/users", "/api/v1/admin/audit-log", "/api/v1/clients"):
        r = client.get(url)
        assert r.status_code == 403, url
        assert r.json()["detail"] == "Tokens de API não acessam a administração."


def test_sair_e_trocar_senha_so_pela_interface(client: TestClient, db: Session) -> None:
    criar_usuario(db, "ana@x.com")
    com_token(client, criar_token(db, "ana@x.com"))
    assert client.post("/api/v1/auth/logout").status_code == 403
    r = client.post(
        "/api/v1/me/password",
        json={"current_password": "uma senha longa de teste", "new_password": "outra senha boa 1"},
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "Esta ação só pode ser feita pela interface."


@pytest.fixture
def _cli_no_banco_de_teste(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.usefixtures("_cli_no_banco_de_teste")
def test_comando_cria_lista_e_revoga(
    client: TestClient, db: Session, capsys: pytest.CaptureFixture[str]
) -> None:
    criar_usuario(db, "ana@x.com")
    cli.main(["token", "create", "--user", "ana@x.com", "--name", "Claude Code", "--read-only"])
    raw = capsys.readouterr().out.splitlines()[-1]
    assert raw.startswith("tf_")
    assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {raw}"}).status_code == 200

    cli.main(["token", "list"])
    linha = capsys.readouterr().out.strip()
    token_id, email, scope, nome, validade, uso = linha.split("\t")
    assert (email, scope, nome) == ("ana@x.com", "read", "Claude Code")
    assert validade.startswith("expira ")
    assert uso.startswith("usado ")  # o GET /me acima

    cli.main(["token", "revoke", token_id])
    assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {raw}"}).status_code == 401
    db.expire_all()
    acoes = list(db.scalars(select(AuditLog.action).order_by(AuditLog.id)))
    assert acoes == ["api_token.created", "api_token.revoked"]
    assert raw not in str(db.scalars(select(AuditLog.after)).all())


def test_desativar_ou_excluir_revoga_os_tokens(client: TestClient, db: Session) -> None:
    criar_usuario(db, "adm@x.com", "admin")
    ana = criar_usuario(db, "ana@x.com")
    bia = criar_usuario(db, "bia@x.com", nome="Bia")
    da_ana, da_bia = criar_token(db, "ana@x.com"), criar_token(db, "bia@x.com")
    entrar(client, "adm@x.com")

    # Reativar a conta não traz o token de volta: ele pode ter vazado
    url = f"/api/v1/users/{ana.public_id}"
    assert client.patch(url, json={"is_active": False}).status_code == 200
    assert client.patch(url, json={"is_active": True}).status_code == 200
    assert client.delete(f"/api/v1/users/{bia.public_id}").status_code == 204

    pela_api = TestClient(client.app)
    for raw in (da_ana, da_bia):
        assert (
            pela_api.get("/api/v1/me", headers={"Authorization": f"Bearer {raw}"}).status_code
            == 401
        )
    db.expire_all()
    assert db.scalar(select(ApiToken).where(ApiToken.revoked_at.is_(None))) is None
    revogados = db.scalars(select(AuditLog).where(AuditLog.action == "api_token.revoked")).all()
    adm = db.scalar(select(User.id).where(User.email == "adm@x.com"))
    assert len(revogados) == 2 and {r.actor_user_id for r in revogados} == {adm}


def test_emails_dos_membros_nao_vao_para_um_token(client: TestClient, db: Session) -> None:
    criar_usuario(db, "adm@x.com", "admin", grupos={"TI": "member"})
    raw = criar_token(db, "adm@x.com")
    entrar(client, "adm@x.com")
    pela_tela = client.get("/api/v1/teams").json()["items"][0]["members"]
    assert [m["email"] for m in pela_tela] == ["adm@x.com"]
    com_token(client, raw)
    pelo_token = client.get("/api/v1/teams").json()["items"][0]["members"]
    assert [m["email"] for m in pelo_token] == [None]
