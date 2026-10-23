"""Consulta da auditoria e comando `chamados admin create`."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from chamados import cli
from chamados.modules.identity.models import User
from tests.conftest import criar_usuario, entrar


def test_auditoria_paginada_para_auditor(client: TestClient, db: Session) -> None:
    criar_usuario(db, "auditor@exemplo.com", "auditor")
    criar_usuario(db)
    entrar(client)
    assert client.get("/api/v1/admin/audit-log").status_code == 403
    for _ in range(3):
        entrar(client)
    client.cookies.clear()
    entrar(client, "auditor@exemplo.com")
    pagina = client.get("/api/v1/admin/audit-log?action=auth.login&limit=2").json()
    assert len(pagina["items"]) == 2 and pagina["next_cursor"]
    seguinte = client.get(
        f"/api/v1/admin/audit-log?action=auth.login&cursor={pagina['next_cursor']}"
    )
    assert all(e["id"] < pagina["next_cursor"] for e in seguinte.json()["items"])
    assert pagina["items"][0]["actor_name"] == "Ana Souza"


@pytest.mark.usefixtures("cli_no_banco_de_teste")
def test_admin_create(db: Session, capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(["admin", "create", "--email", "ti@exemplo.com", "--name", "Administrador"])
    saida = capsys.readouterr().out
    assert "http://teste/convite/" in saida
    admin = db.scalar(select(User).where(User.email == "ti@exemplo.com"))
    assert admin and admin.role.code == "admin" and admin.password_hash is None
    with pytest.raises(SystemExit, match="Já existe"):
        cli.main(["admin", "create", "--email", "ti@exemplo.com", "--name", "Outro"])
