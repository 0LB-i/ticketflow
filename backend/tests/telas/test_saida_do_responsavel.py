"""Quem sai do sistema ou de um grupo não deixa chamado aberto sem dono (tickets.service.release):
assume o próximo responsável da lista ou um supervisor do grupo; sem supervisor, a tela avisa."""

import base64
import json
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.apoio import API, eventos, registrar
from tests.conftest import criar_usuario, entrar


def _responsaveis(client: TestClient, numero: int) -> tuple[str, list[str]]:
    t = client.get(f"{API}/{numero}").json()
    return t["assignee"]["display_name"], [c["display_name"] for c in t["co_assignees"]]


def _avisos(client: TestClient) -> list[list[str]]:
    raw = client.cookies.get("tf_aviso")
    return json.loads(base64.urlsafe_b64decode(raw)) if raw else []


def test_excluir_e_desativar_passam_os_chamados_abertos(
    client: TestClient,
    cenario: dict[str, Any],
    db: Session,
) -> None:
    duda = str(criar_usuario(db, "duda@x.com", nome="Duda", grupos={"TI": "member"}).public_id)
    so_ana = registrar(client, cenario)["number"]
    com_duda = registrar(client, cenario, co_assignee_ids=[duda])["number"]
    da_bia = registrar(client, cenario, assignee=cenario["bia"], co_assignee_ids=[cenario["ana"]])
    concluido = registrar(client, cenario)["number"]
    concluir = {"action": "close", "comment": "Feito", "resolution_code_id": 1}
    assert client.post(f"{API}/{concluido}/transitions", json=concluir).status_code == 200

    criar_usuario(db, "adm@x.com", "admin", nome="Adm")
    entrar(client, "adm@x.com")
    assert client.delete(f"/api/v1/users/{cenario['ana']}").status_code == 204

    assert _responsaveis(client, so_ana) == ("Bia", [])  # a supervisora do grupo
    assert _responsaveis(client, com_duda) == ("Duda", [])  # o próximo da lista
    assert _responsaveis(client, da_bia["number"]) == ("Bia", [])  # só sai da lista
    assert _responsaveis(client, concluido) == ("Ana", [])  # o concluído fica como está
    ultimo = eventos(client, so_ana)[-1]
    assert ultimo["type"] == "ticket.assignees_changed"
    assert ultimo["actor"]["display_name"] == "Adm"
    assert [r["name"] for r in ultimo["payload"]["removed"]] == ["Ana"]
    assert [r["name"] for r in ultimo["payload"]["added"]] == ["Bia"]
    assert ultimo["payload"]["assignee"]["to"]["name"] == "Bia"

    # Desativar também: a Duda, agora sozinha no chamado, passa para a supervisora
    assert client.patch(f"/api/v1/users/{duda}", json={"is_active": False}).status_code == 200
    assert _responsaveis(client, com_duda) == ("Bia", [])


def test_tirar_do_grupo_sem_supervisor_avisa_na_tela(
    client: TestClient,
    cenario: dict[str, Any],
    db: Session,
) -> None:
    ti = registrar(client, cenario, assignee=cenario["bia"])  # do TI: não é do Caio
    entrar(client, "caio@x.com")
    infra = registrar(client, cenario, team_id=cenario["infra"], category_id=None)["number"]

    criar_usuario(db, "adm@x.com", "admin", nome="Adm")
    entrar(client, "adm@x.com")
    url = f"/admin/grupos/{cenario['infra']}/membros/{cenario['caio']}/remover"
    r = client.post(url, data={"csrf_token": client.cookies["tf_csrf"]}, follow_redirects=False)
    assert r.status_code == 303
    # A Infra não tem supervisor: o chamado continua com o Caio, e a tela diz qual
    assert _responsaveis(client, infra) == ("Caio", [])
    assert _avisos(client) == [
        [
            "error",
            f"Os chamados #{infra} continuam com Caio: o grupo não tem supervisor para "
            "recebê-los. Reatribua-os.",
        ]
    ]
    assert _responsaveis(client, ti["number"]) == ("Bia", [])
