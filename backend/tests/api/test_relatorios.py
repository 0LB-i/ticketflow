"""Relatórios: horas, horas extras, clientes, permissões, PDF e CSV (docs/14 §14.7 e §14.8).

Cenário (a fixture `cenario`): Ana (membro) e Bia (supervisora) no TI, Caio na Infra, um auditor.
"""

import csv
import io
import uuid
from datetime import date, datetime, time, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from chamados.config import Settings
from chamados.modules.audit.models import AuditLog
from chamados.modules.identity.models import User
from chamados.modules.organization.models import TeamMember
from chamados.modules.reports import model_pdf
from chamados.modules.reports.service import TZ, outside_minutes
from chamados.modules.system.models import WorkSchedule
from chamados.modules.system.work_hours import Calendar, load_calendar
from chamados.modules.tickets.models import Ticket
from tests.apoio import API, base, dia_util_passado, em, registrar, rodar, tarefa
from tests.conftest import consultas, criar_cliente, criar_usuario, entrar, grupo

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
    assert outside_minutes(fim, minutos, Calendar(installation=[])) == fora


def test_feriado_e_todo_fora() -> None:
    feriado = Calendar(installation=[], holidays=frozenset({SEGUNDA}))
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
    opcoes = client.get(f"{REPORTS}/options").json()
    assert opcoes["teams"] == []
    assert opcoes["people"] == [{"id": cenario["caio"], "name": "Caio"}]

    # Bia supervisiona o TI: vê a Ana, não vê a Infra
    entrar(client, "bia@x.com")
    assert [p["name"] for p in relatorio(client, dia)["people"]] == ["Ana"]
    assert relatorio(client, dia, person=cenario["ana"])["totals"]["minutes"] == 60
    relatorio(client, dia, 403, person=cenario["caio"])
    relatorio(client, dia, 403, team=cenario["infra"])
    # Com vários, cada um precisa estar ao alcance.
    assert (
        relatorio(client, dia, person=[cenario["ana"], cenario["bia"]])["totals"]["minutes"] == 60
    )
    relatorio(client, dia, 403, person=[cenario["ana"], cenario["caio"]])
    relatorio(client, dia, 403, team=[cenario["ti"], cenario["infra"]])
    opcoes = client.get(f"{REPORTS}/options").json()
    assert [t["name"] for t in opcoes["teams"]] == ["TI"]
    assert [p["name"] for p in opcoes["people"]] == ["Ana", "Bia"]

    # Admin e auditor veem tudo
    for quem in ("admin@x.com", "auditor@x.com"):
        entrar(client, quem)
        assert [p["name"] for p in relatorio(client, dia)["people"]] == ["Ana", "Caio"]
        assert relatorio(client, dia, team=cenario["infra"])["totals"]["minutes"] == 30
        assert (
            relatorio(client, dia, team=[cenario["ti"], cenario["infra"]])["totals"]["tasks"] == 2
        )


def test_varios_clientes_sem_cliente_e_status(
    client: TestClient, cenario: dict[str, Any], db: Session
) -> None:
    dia = dia_util_passado()
    padaria = criar_cliente(db, "Padaria", "11222333000181")
    mercado = criar_cliente(db, "Mercado", "11444777000161")
    a = registrar(client, cenario, client_id=padaria)["number"]
    tarefa(client, a, 40, em(dia, 10))
    b = registrar(client, cenario, client_id=mercado)["number"]
    tarefa(client, b, 20, em(dia, 11))
    c = registrar(client, cenario)["number"]
    tarefa(client, c, 10, em(dia, 12))
    # Um chamado antigo, de antes do cliente obrigatório.
    db.execute(update(Ticket).where(Ticket.number == c).values(client_id=None))
    db.commit()
    client.post(
        f"{API}/{a}/transitions",
        json={"action": "close", "comment": "Pronto", "resolution_code_id": 1},
    )

    def minutos(**query: Any) -> int:
        result: int = relatorio(client, dia, **query)["totals"]["minutes"]
        return result

    assert minutos(client=[padaria, mercado]) == 60
    assert minutos(client=padaria, no_client=True) == 50
    assert minutos(no_client=True) == 10
    relatorio(client, dia, 404, client=[padaria, str(uuid.uuid4())])

    opcoes = client.get(f"{REPORTS}/options").json()
    assert [c["name"] for c in opcoes["clients"]] == ["Cliente Padrão", "Mercado", "Padaria"]
    status = {s["name"]: s["id"] for s in opcoes["statuses"]}
    # O status é o atual do chamado. `status` é o código HTTP no relatorio(): vai por params.
    params = {"start": dia.isoformat(), "end": dia.isoformat()}
    for escolhidos, esperado in (
        (["Concluído"], 40),
        (["Pendente"], 30),
        (["Pendente", "Concluído"], 70),
    ):
        r = client.get(REPORTS, params={**params, "status": [status[n] for n in escolhidos]})
        assert r.json()["totals"]["minutes"] == esperado, escolhidos
    assert client.get(REPORTS, params={**params, "status": 999}).status_code == 404


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


def test_csv(client: TestClient, cenario: dict[str, Any], db: Session) -> None:
    dia = dia_util_passado()
    t = registrar(client, cenario, title='=1+1 Planilha; "aspas"')["number"]
    tarefa(client, t, 90, em(dia, 19))  # 60 min fora do expediente
    tarefa(client, t, 30, em(dia, 10))
    periodo = {"start": dia.isoformat(), "end": dia.isoformat()}

    def baixar(tabela: str, idioma: str) -> list[list[str]]:
        r = client.get(f"{REPORTS}/csv", params={**periodo, "table": tabela, "locale": idioma})
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "text/csv; charset=utf-8"
        assert r.content.startswith(b"\xef\xbb\xbf")  # BOM: o Excel reconhece o UTF-8
        texto = r.content.decode("utf-8-sig")
        return list(csv.reader(io.StringIO(texto), delimiter=";" if idioma == "pt-BR" else ","))

    # Todas as tarefas, em ordem; o título com cara de fórmula ganha o apóstrofo.
    titulo = '\'=1+1 Planilha; "aspas"'
    assert baixar("tasks", "pt-BR") == [
        [
            "Quando",
            "Pessoa",
            "Chamado",
            "Título",
            "Cliente",
            "Tempo",
            "Tempo (min)",
            "Fora do expediente",
            "Fora do expediente (min)",
        ],
        [
            f"{dia:%d/%m/%Y} 10:00",
            "Ana",
            str(t),
            titulo,
            "Cliente Padrão",
            "0,50",
            "30",
            "0,00",
            "0",
        ],
        [
            f"{dia:%d/%m/%Y} 19:00",
            "Ana",
            str(t),
            titulo,
            "Cliente Padrão",
            "1,50",
            "90",
            "1,00",
            "60",
        ],
    ]
    # As horas extras, em inglês: vírgula como separador e ponto decimal.
    extras = baixar("overtime", "en")
    assert extras[0][0] == "When" and len(extras) == 2
    assert extras[1][0] == f"{dia:%Y-%m-%d} 19:00"
    assert extras[1][5:] == ["1.50", "90", "1.00", "60"]
    assert baixar("people", "pt-BR") == [
        [
            "Pessoa",
            "Horas",
            "Horas (min)",
            "Horas extras",
            "Horas extras (min)",
            "Tarefas",
            "Chamados concluídos",
        ],
        ["Ana", "2,00", "120", "1,00", "60", "2", "0"],
    ]
    assert baixar("clients", "pt-BR")[1] == ["Cliente Padrão", "2,00", "120", "0", "0"]

    r = client.get(f"{REPORTS}/csv", params=periodo)
    assert r.status_code == 422  # sem a tabela
    r = client.get(f"{REPORTS}/csv", params={**periodo, "table": "tasks"})
    assert (
        f"relatorio-tarefas-{dia.isoformat()}-a-{dia.isoformat()}.csv"
        in (r.headers["content-disposition"])
    )
    # Cada download vai para a auditoria, com o formato e a tabela.
    registros = db.scalars(
        select(AuditLog).where(AuditLog.action == "report.exported").order_by(AuditLog.id)
    ).all()
    assert len(registros) == 5
    ultimo = registros[-1].after or {}
    assert ultimo["format"] == "csv" and ultimo["table"] == "tasks"
    assert ultimo["start"] == dia.isoformat()


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

    monkeypatch.setattr(model_pdf, "render_hours", render)
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

    # O relatório usa o expediente novo a partir do dia dele: 17:30–19:00 fica todo fora
    dia = dia_util_passado()
    r = client.put(
        "/api/v1/admin/settings/work-hours", json={**novo, "valid_from": dia.isoformat()}
    )
    assert r.status_code == 200, r.text
    entrar(client, "ana@x.com")
    t = registrar(client, cenario, assignee="me")["number"]
    tarefa(client, t, 90, em(dia, 19))
    assert relatorio(client, dia)["totals"]["overtime_minutes"] == 90


def test_hora_extra_pelo_expediente_do_grupo_e_proprio(
    client: TestClient, cenario: dict[str, Any], db: Session
) -> None:
    """O TI tem expediente (10:00–19:00, seg–sáb): vale para a Ana. A Bia tem um próprio
    (06:00–12:00) e, a partir de terça, outro (00:00–08:00). O total vem do pré-filtro (só as
    tarefas que podem ter hora extra vão ao Python) e tem de bater com o de todas as tarefas
    calculadas em Python (o CSV): o pré-filtro só pode deixar passar a mais."""
    dia = dia_util_passado()
    terca = dia + timedelta(days=1)
    bia = db.scalar(select(User).where(User.email == "bia@x.com"))
    assert bia is not None
    todos = [0, 1, 2, 3, 4, 5, 6]
    db.add_all(
        [
            WorkSchedule(
                team_id=grupo(db, "TI").id, weekdays=todos[:6], start=time(10), end=time(19)
            ),
            WorkSchedule(
                user_id=bia.id, valid_from=dia, weekdays=todos, start=time(6), end=time(12)
            ),
            WorkSchedule(
                user_id=bia.id, valid_from=terca, weekdays=todos, start=time(0), end=time(8)
            ),
        ]
    )
    db.commit()
    t = registrar(client, cenario, assignee="me")["number"]
    tarefa(client, t, 60, em(dia, 18, 30))  # Ana, dentro do TI (na instalação, 30 fora)
    tarefa(client, t, 60, em(dia, 10, 30))  # Ana, 09:30–10:30: 30 fora (na instalação, 0)
    entrar(client, "bia@x.com")
    tarefa(client, t, 60, em(dia, 7))  # Bia, dentro do próprio
    tarefa(client, t, 120, em(dia, 13))  # Bia, 11:00–13:00: 60 fora (na instalação, 0)
    tarefa(client, t, 180, em(terca, 1))  # Bia, 22:00–01:00: na terça, 00:00–01:00 dentro
    criar_usuario(db, "admin@x.com", "admin", nome="Admin")
    entrar(client, "admin@x.com")

    periodo = {"start": dia.isoformat(), "end": terca.isoformat()}
    dados = client.get(REPORTS, params=periodo).json()
    assert dados["totals"]["overtime_minutes"] == 210
    assert {p["name"]: p["overtime_minutes"] for p in dados["people"]} == {"Ana": 30, "Bia": 180}
    assert sorted(r["overtime_minutes"] for r in dados["overtime_tasks"]) == [30, 60, 120]
    r = client.get(f"{REPORTS}/csv", params={**periodo, "table": "tasks", "locale": "en"})
    linhas = list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert sum(int(x["Outside working hours (min)"]) for x in linhas) == 210


def test_grupo_desativado_e_dois_grupos(
    client: TestClient, cenario: dict[str, Any], db: Session, settings: Settings
) -> None:
    """Só os grupos ativos contam; quem está em dois com expediente segue o da instalação."""
    ti, infra = grupo(db, "TI"), grupo(db, "Infra")
    for team in (ti, infra):
        db.add(WorkSchedule(team_id=team.id, weekdays=[0], start=time(9), end=time(10)))
    ana = db.scalar(select(User).where(User.email == "ana@x.com"))
    assert ana is not None
    db.add(TeamMember(team_id=infra.id, user_id=ana.id))
    db.commit()

    async def ler(sessions: async_sessionmaker[AsyncSession]) -> Calendar:
        async with sessions() as session:
            return await load_calendar(session)

    segunda = dia_util_passado()
    cal = rodar(settings, ler)
    assert cal.source(ana.id, segunda).conflict == tuple(sorted((ti.id, infra.id)))
    assert cal.source(ana.id, segunda).kind == "installation"
    infra.is_active = False
    db.commit()
    cal = rodar(settings, ler)
    assert cal.source(ana.id, segunda).kind == "team"
    assert cal.source(ana.id, segunda).team_id == ti.id


def test_expediente_vigencias(client: TestClient, db: Session) -> None:
    """O PUT grava uma vigência da instalação a partir de hoje (ou de `valid_from`); o GET
    responde a de hoje. Uma vigência igual à anterior não é gravada, e a da mesma data é
    substituída."""
    criar_usuario(db, "admin@x.com", "admin", nome="Admin")
    entrar(client, "admin@x.com")
    hoje = datetime.now(TZ).date()
    amanha = hoje + timedelta(days=1)
    url = "/api/v1/admin/settings/work-hours"
    novo = {"weekdays": [0, 1, 2, 3, 4], "start": "07:00", "end": "17:00", "holidays": []}

    def vigencias() -> list[tuple[date | None, str | None]]:
        db.expire_all()
        linhas = db.scalars(select(WorkSchedule).order_by(WorkSchedule.valid_from))
        return [(v.valid_from, f"{v.start:%H:%M}" if v.start else None) for v in linhas]

    assert client.put(url, json=novo).status_code == 200
    assert vigencias() == [(hoje, "07:00")]
    assert client.get("/api/v1/work-hours").json()["start"] == "07:00:00"

    # Só os feriados mudam: nenhuma vigência nova, e a auditoria registra só eles.
    novo["holidays"] = ["2026-12-25"]
    assert client.put(url, json=novo).status_code == 200
    assert vigencias() == [(hoje, "07:00")]
    ultimo = db.scalars(select(AuditLog).order_by(AuditLog.id.desc())).first()
    assert ultimo is not None
    assert ultimo.before == {"holidays": []}
    assert ultimo.after == {"holidays": ["2026-12-25"]}

    # Uma vigência futura não muda o de hoje; trocar a mesma data a substitui, e voltar ao
    # anterior a tira.
    futuro = {**novo, "start": "09:00", "valid_from": amanha.isoformat()}
    assert client.put(url, json=futuro).status_code == 200
    assert vigencias() == [(hoje, "07:00"), (amanha, "09:00")]
    assert client.get("/api/v1/work-hours").json()["start"] == "07:00:00"
    ultimo = db.scalars(select(AuditLog).order_by(AuditLog.id.desc())).first()
    assert ultimo is not None
    assert ultimo.before == {
        "work_hours": {
            "valid_from": amanha.isoformat(),
            "weekdays": [0, 1, 2, 3, 4],
            "start": "07:00",
            "end": "17:00",
        }
    }
    assert ultimo.after == {"work_hours": {**ultimo.before["work_hours"], "start": "09:00"}}
    r = client.put(url, json={**futuro, "start": "10:00"})
    assert r.status_code == 200
    assert vigencias() == [(hoje, "07:00"), (amanha, "10:00")]
    assert client.put(url, json={**novo, "valid_from": amanha.isoformat()}).status_code == 200
    assert vigencias() == [(hoje, "07:00")]
    # Os feriados continuam na chave de sempre.
    assert client.get("/api/v1/work-hours").json()["holidays"] == ["2026-12-25"]
