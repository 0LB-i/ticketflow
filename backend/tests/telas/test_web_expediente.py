"""Expediente nos painéis de grupo (admin.organization) e de usuário (admin.users): as vigências,
o que vale hoje e de onde vem, e o aviso de quem está em dois grupos com expediente."""

import re
from datetime import datetime, time
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from chamados.modules.audit.models import AuditLog
from chamados.modules.identity.models import User
from chamados.modules.organization.models import Team
from chamados.modules.system.models import WorkSchedule
from chamados.modules.system.work_hours import TZ
from tests.conftest import criar_usuario, entrar, grupo


def _form(client: TestClient, **dados: Any) -> dict[str, Any]:
    return {"csrf_token": client.cookies["tf_csrf"], **dados}


def _aviso(html: str) -> str:
    achado = re.search(r'data-aviso="\w+".*?<p class="font-semibold">(.*?)</p>', html, re.S)
    return achado.group(1) if achado else ""


def _admin(client: TestClient, db: Session) -> User:
    user = criar_usuario(db, "admin@exemplo.com", "admin", nome="Admin")
    entrar(client, "admin@exemplo.com")
    return user


def _vigencias(db: Session, **dono: int) -> list[WorkSchedule]:
    db.expire_all()
    return list(
        db.scalars(select(WorkSchedule).filter_by(**dono).order_by(WorkSchedule.valid_from))
    )


def _hoje() -> str:
    return datetime.now(TZ).date().isoformat()


SEG_A_QUI = {"weekdays": ["0", "1", "2", "3"], "start": "07:00", "end": "16:00"}


def test_so_quem_tem_a_permissao(client: TestClient, db: Session) -> None:
    criar_usuario(db, grupos={"TI": "supervisor"})
    entrar(client)
    ti = grupo(db, "TI")
    ana = db.scalar(select(User).where(User.email == "ana@exemplo.com"))
    assert ana is not None
    dados = _form(client, valid_from=_hoje(), **SEG_A_QUI)
    assert client.post(f"/admin/grupos/{ti.public_id}/expediente", data=dados).status_code == 403
    r = client.post(f"/admin/usuarios/{ana.public_id}/expediente", data=dados)
    assert r.status_code == 403
    assert _vigencias(db) == []


def test_vigencia_do_grupo(client: TestClient, db: Session) -> None:
    _admin(client, db)
    criar_usuario(db, "bia@x.com", nome="Bia", grupos={"Suporte": "member"})
    suporte = grupo(db, "Suporte")
    url = f"/admin/grupos?editar={suporte.public_id}"
    r = client.get(url)
    assert "Segue o da instalação (Seg–Sex 08:00–18:00)" in r.text
    assert 'action="/admin/grupos/' in r.text and "/expediente" in r.text

    dados = _form(client, valid_from=_hoje(), **SEG_A_QUI)
    r = client.post(
        f"/admin/grupos/{suporte.public_id}/expediente", data=dados, follow_redirects=False
    )
    assert r.headers["location"] == url  # volta com o painel aberto
    r = client.get(r.headers["location"])
    assert "Próprio (Seg–Qui 07:00–16:00)" in r.text
    assert "1 membro segue o expediente do grupo hoje." in r.text
    assert "Vale hoje" in r.text
    [vigencia] = _vigencias(db, team_id=suporte.id)
    assert (vigencia.weekdays, vigencia.start, vigencia.end) == ([0, 1, 2, 3], time(7), time(16))
    assert str(vigencia.valid_from) == _hoje()
    log = db.scalar(select(AuditLog).where(AuditLog.action == "team.work_hours_set"))
    assert log is not None and log.target_id == str(suporte.public_id)
    assert log.before == {"valid_from": _hoje(), "work_hours": None}

    # Sem expediente próprio a partir de uma data: volta ao da instalação dali em diante.
    client.post(
        f"/admin/grupos/{suporte.public_id}/expediente",
        data=_form(client, valid_from="2099-01-01", sem_proprio="1", **SEG_A_QUI),
    )
    vigencias = _vigencias(db, team_id=suporte.id)
    assert [(str(v.valid_from), v.weekdays) for v in vigencias] == [
        (_hoje(), [0, 1, 2, 3]),
        ("2099-01-01", None),
    ]
    r = client.get(url)
    assert "A partir de 01/01/2099" in r.text
    assert "Sem expediente próprio</span>" in r.text


def test_erro_devolve_o_painel(client: TestClient, db: Session) -> None:
    _admin(client, db)
    suporte = grupo(db, "Suporte")
    base = f"/admin/grupos/{suporte.public_id}/expediente"
    r = client.post(base, data=_form(client, valid_from=_hoje(), **{**SEG_A_QUI, "end": "06:00"}))
    assert r.status_code == 422
    assert "data-abre-ao-carregar" in r.text
    assert "O fim precisa ser depois do início.</p>" in r.text
    assert 'value="06:00"' in r.text  # o que foi digitado
    r = client.post(base, data=_form(client, valid_from=_hoje(), start="08:00", end="12:00"))
    assert "Marque pelo menos um dia de trabalho." in r.text
    r = client.post(base, data=_form(client, valid_from="31/02/2026", **SEG_A_QUI))
    assert r.status_code == 422
    assert "Informe uma data válida." in r.text
    assert _vigencias(db) == []


def test_vigencia_da_pessoa(client: TestClient, db: Session) -> None:
    _admin(client, db)
    bia = criar_usuario(db, "bia@x.com", nome="Bia")
    url = f"/admin/usuarios?editar={bia.public_id}"
    r = client.get(url)
    assert "Segue o da instalação (Seg–Sex 08:00–18:00)" in r.text
    # Os campos ficam dentro do formulário do usuário e apontam o formulário do expediente.
    acao = f'<form id="form-expediente" method="post" action="/admin/usuarios/{bia.public_id}/'
    assert acao in r.text
    assert re.search(r'name="valid_from" type="date" [^>]* form="form-expediente"', r.text)
    assert 'name="weekdays" value="4" checked form="form-expediente"' in r.text

    r = client.post(
        f"/admin/usuarios/{bia.public_id}/expediente",
        data=_form(client, valid_from=_hoje(), **SEG_A_QUI),
        follow_redirects=False,
    )
    assert r.headers["location"] == url
    r = client.get(url)
    assert "Próprio (Seg–Qui 07:00–16:00)" in r.text
    [vigencia] = _vigencias(db, user_id=bia.id)
    assert vigencia.weekdays == [0, 1, 2, 3]
    log = db.scalar(select(AuditLog).where(AuditLog.action == "user.work_hours_set"))
    assert log is not None and log.target_id == str(bia.public_id)
    assert log.after == {
        "valid_from": _hoje(),
        "work_hours": {"weekdays": [0, 1, 2, 3], "start": "07:00", "end": "16:00"},
    }

    # Erro: o painel volta aberto, com a mensagem na seção.
    r = client.post(
        f"/admin/usuarios/{bia.public_id}/expediente",
        data=_form(client, valid_from="", **SEG_A_QUI),
    )
    assert r.status_code == 422
    assert "data-abre-ao-carregar" in r.text and "Informe uma data válida." in r.text


def test_origem_do_grupo_e_aviso_de_dois_grupos(client: TestClient, db: Session) -> None:
    _admin(client, db)
    bia = criar_usuario(db, "bia@x.com", nome="Bia", grupos={"Suporte": "member"})
    suporte = grupo(db, "Suporte")
    client.post(
        f"/admin/grupos/{suporte.public_id}/expediente",
        data=_form(client, valid_from=_hoje(), **SEG_A_QUI),
    )
    url = f"/admin/usuarios?editar={bia.public_id}"
    assert "Segue o do grupo Suporte (Seg–Qui 07:00–16:00)" in client.get(url).text

    # Num segundo grupo com expediente: vale o da instalação, e a tela pede um próprio.
    criar_usuario(db, "caio@x.com", nome="Caio", grupos={"Redes": "member"})
    redes = db.scalar(select(Team).where(Team.name == "Redes"))
    assert redes is not None
    client.post(
        f"/admin/grupos/{redes.public_id}/membros",
        data=_form(client, user_id=str(bia.public_id), role="member"),
    )
    client.post(
        f"/admin/grupos/{redes.public_id}/expediente",
        data=_form(client, valid_from=_hoje(), weekdays=["4"], start="10:00", end="14:00"),
    )
    r = client.get(url)
    assert "Segue o da instalação (Seg–Sex 08:00–18:00)" in r.text
    assert "Está em mais de um grupo com expediente (Redes, Suporte)" in r.text
    assert "Defina o expediente" in client.get("/admin/usuarios").text  # o sinal na lista

    # Com um próprio, o aviso some.
    client.post(
        f"/admin/usuarios/{bia.public_id}/expediente",
        data=_form(client, valid_from=_hoje(), **SEG_A_QUI),
    )
    r = client.get(url)
    assert "Próprio (Seg–Qui 07:00–16:00)" in r.text
    assert "mais de um grupo" not in r.text
