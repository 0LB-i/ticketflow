"""Relatórios: horas, horas extras, clientes, permissões e PDF (docs/14 §14.7).

Cenário (a fixture `cenario`): Ana (membro) e Bia (supervisora) no TI, Caio na Infra, um auditor.
"""

from datetime import date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from chamados.modules.audit.models import AuditLog
from chamados.modules.reports import pdf
from chamados.modules.reports.service import TZ, outside_minutes
from chamados.modules.system.work_hours import DEFAULT, WorkHours
from tests.apoio import API, base, dia_util_passado, em, registrar, tarefa
from tests.conftest import consultas, criar_cliente, criar_usuario, entrar

REPORTS = "/api/v1/reports"
SEGUNDA = date(2026, 10, 5)


@pytest.mark.parametrize(
    ("fim", "minutos", "fora"),
    [
        (em(SEGUNDA, 10), 60, 0),  # dentro do expediente
        (em(SEGUNDA, 19), 90, 60),  # 17:30–19:00
        (em(SEGUNDA, 8, 30), 60, 30),  # 07:30–08:30
        (em(SEGUNDA + timedelta(days=5), 10), 45, 45),  # sábado
        (em(SEGUNDA + timedelta(days=1), 1), 180, 180),  # 22:00–01:00, virando o dia
        (em(SEGUNDA, 20), 13 * 60, 3 * 60),  # 07:00–20:00
    ],
)
def test_minutos_fora_do_expediente(fim: datetime, minutos: int, fora: int) -> None:
    assert outside_minutes(fim, minutos, DEFAULT) == fora


def test_feriado_e_todo_fora() -> None:
    feriado = WorkHours(**{**DEFAULT.model_dump(), "holidays": [SEGUNDA]})
    assert outside_minutes(em(SEGUNDA, 10), 60, feriado) == 60


# --- números --------------------------------------------------------------------------------


def relatorio(c: TestClient, dia: date, status: int = 200, **query: Any) -> dict[str, Any]:
    r = c.get(REPORTS, params={"start": dia.isoformat(), "end": dia.isoformat(), **query})
    assert r.status_code == status, r.text
    result: dict[str, Any] = r.json()
    return result


def test_horas_por_pessoa_cliente_e_dia(
    client: TestClient,
    cenario: dict[str, Any],
    db: Session,
) -> None:
    dia = dia_util_passado()
    padaria = criar_cliente(db, "Padaria", "11222333000181")
    t = registrar(client, cenario, assignee="me", client_id=padaria)["number"]
    tarefa(client, t, 30, em(dia, 10))
    tarefa(client, t, 90, em(dia, 19))  # 60 min depois das 18:00
    client.post(
        f"{API}/{t}/transitions",
        json={"action": "close", "comment": "Pronto", "resolution_code_id": 1},
    )
    outro = registrar(client, cenario, assignee="me")["number"]
    tarefa(client, outro, 15, em(dia, 11))

    with consultas(client) as sql:
        r = relatorio(client, dia)
    # Só as colunas usadas: o texto das tarefas (até 50 mil caracteres) não é lido
    assert not [q for q in sql if "ticket_comments.body" in q]
    assert r["totals"]["minutes"] == 135
    assert r["totals"]["overtime_minutes"] == 60
    assert r["totals"]["tasks"] == 3
    assert [(p["name"], p["minutes"], p["overtime_minutes"]) for p in r["people"]] == [
        ("Ana", 135, 60)
    ]
    assert [(c["name"], c["minutes"]) for c in r["clients"]] == [
        ("Padaria", 120),
        ("Cliente Padrão", 15),
    ]
    assert r["days"] == [{"date": dia.isoformat(), "minutes": 135, "overtime_minutes": 60}]
    assert [(o["ticket_number"], o["overtime_minutes"]) for o in r["overtime_tasks"]] == [(t, 60)]

    # Registrados e concluídos contam pela data de hoje
    hoje = relatorio(client, datetime.now(TZ).date())
    assert hoje["totals"]["tickets_opened"] == 2
    assert hoje["totals"]["tickets_closed"] == 1
    assert hoje["people"][0]["tickets_closed"] == 1
    assert hoje["people"][0]["tasks"] == 1  # o comentário da conclusão

    # Filtro por cliente
    so_padaria = relatorio(client, dia, client=padaria)
    assert so_padaria["totals"]["minutes"] == 120


def test_cada_um_ve_o_seu_e_o_supervisor_o_grupo(
    client: TestClient,
    cenario: dict[str, Any],
    db: Session,
) -> None:
    dia = dia_util_passado()
    da_ana = registrar(client, cenario, assignee="me")["number"]
    tarefa(client, da_ana, 60, em(dia, 10))
    entrar(client, "caio@x.com")
    da_infra = client.post(
        API, json={**base(cenario), "title": "Servidor", "team_id": cenario["infra"]}
    ).json()
    tarefa(client, da_infra["number"], 30, em(dia, 10))
    criar_usuario(db, "admin@x.com", "admin", nome="Admin")

    # Caio só vê o próprio trabalho
    assert [p["name"] for p in relatorio(client, dia)["people"]] == ["Caio"]
    relatorio(client, dia, 403, person=cenario["ana"])
    relatorio(client, dia, 403, team=cenario["ti"])
    assert client.get(f"{REPORTS}/options").json() == {
        "teams": [],
        "people": [{"id": cenario["caio"], "name": "Caio"}],
    }

    # Bia supervisiona o TI: vê a Ana, não vê a Infra
    entrar(client, "bia@x.com")
    assert [p["name"] for p in relatorio(client, dia)["people"]] == ["Ana"]
    assert relatorio(client, dia, person=cenario["ana"])["totals"]["minutes"] == 60
    relatorio(client, dia, 403, person=cenario["caio"])
    relatorio(client, dia, 403, team=cenario["infra"])
    opcoes = client.get(f"{REPORTS}/options").json()
    assert [t["name"] for t in opcoes["teams"]] == ["TI"]
    assert [p["name"] for p in opcoes["people"]] == ["Ana", "Bia"]

    # Admin e auditor veem tudo
    for quem in ("admin@x.com", "auditor@x.com"):
        entrar(client, quem)
        assert [p["name"] for p in relatorio(client, dia)["people"]] == ["Ana", "Caio"]
        assert relatorio(client, dia, team=cenario["infra"])["totals"]["minutes"] == 30


def test_periodo_invalido(client: TestClient, cenario: dict[str, Any]) -> None:
    r = client.get(REPORTS, params={"start": "2026-10-10", "end": "2026-10-01"})
    assert r.status_code == 422
    r = client.get(REPORTS, params={"start": "2025-01-01", "end": "2026-10-01"})
    assert r.status_code == 422
    # O último dia do calendário: o fim do período (o dia seguinte) não existe.
    r = client.get(REPORTS, params={"start": "9999-12-31", "end": "9999-12-31"})
    assert r.status_code == 422 and r.json()["detail"] == "Data inválida."


def test_pdf(client: TestClient, cenario: dict[str, Any], db: Session) -> None:
    dia = dia_util_passado()
    t = registrar(client, cenario, assignee="me", title="Ação & reação <teste>")["number"]
    tarefa(client, t, 90, em(dia, 19))
    for idioma in ("pt-BR", "en"):
        r = client.get(
            f"{REPORTS}/pdf",
            params={"start": dia.isoformat(), "end": dia.isoformat()},
            headers={"Accept-Language": idioma},
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        assert r.content.startswith(b"%PDF")
        assert f"relatorio-{dia.isoformat()}" in r.headers["content-disposition"]
    acoes = db.scalars(select(AuditLog.action).where(AuditLog.action == "report.exported")).all()
    assert len(acoes) == 2


def test_pdf_no_idioma_pedido(
    client: TestClient,
    cenario: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Um link da tela não escolhe o Accept-Language: o idioma da pessoa vai em `locale`.
    idiomas: list[str] = []

    def render(*args: Any) -> bytes:
        idiomas.append(args[-1])
        return b"%PDF"

    monkeypatch.setattr(pdf, "render", render)
    dia = dia_util_passado().isoformat()
    for params in ({}, {"locale": "en"}, {"locale": "pt-BR"}):
        r = client.get(
            f"{REPORTS}/pdf",
            params={"start": dia, "end": dia, **params},
            headers={"Accept-Language": "en"},
        )
        assert r.status_code == 200, r.text
    assert idiomas == ["en", "en", "pt-BR"]
    r = client.get(f"{REPORTS}/pdf", params={"start": dia, "end": dia, "locale": "fr"})
    assert r.status_code == 422


# --- expediente -----------------------------------------------------------------------------


def test_expediente(client: TestClient, cenario: dict[str, Any], db: Session) -> None:
    padrao = client.get("/api/v1/work-hours").json()
    assert padrao == {
        "weekdays": [0, 1, 2, 3, 4],
        "start": "08:00:00",
        "end": "18:00:00",
        "holidays": [],
    }
    novo = {"weekdays": [5, 0, 1], "start": "07:00", "end": "17:00", "holidays": ["2026-12-25"]}
    assert client.put("/api/v1/admin/settings/work-hours", json=novo).status_code == 403

    criar_usuario(db, "admin@x.com", "admin", nome="Admin")
    entrar(client, "admin@x.com")
    r = client.put("/api/v1/admin/settings/work-hours", json=novo)
    assert r.status_code == 200, r.text
    assert r.json()["weekdays"] == [0, 1, 5]
    assert client.get("/api/v1/work-hours").json()["start"] == "07:00:00"
    r = client.put("/api/v1/admin/settings/work-hours", json={**novo, "end": "06:00"})
    assert r.status_code == 422
    r = client.put("/api/v1/admin/settings/work-hours", json={**novo, "weekdays": [7]})
    assert r.status_code == 422
    assert db.scalar(select(AuditLog).where(AuditLog.action == "settings.updated")) is not None

    # O relatório usa o expediente novo: 17:30–19:00 fica todo fora
    entrar(client, "ana@x.com")
    dia = dia_util_passado()
    t = registrar(client, cenario, assignee="me")["number"]
    tarefa(client, t, 90, em(dia, 19))
    assert relatorio(client, dia)["totals"]["overtime_minutes"] == 90
