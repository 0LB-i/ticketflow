"""Relatórios (docs/14 §14.7 e §14.8): horas por pessoa, por cliente e por dia, horas extras e o
PDF e o CSV com os mesmos filtros. Cada um vê o próprio trabalho; o supervisor, o dos grupos que
supervisiona; admin e auditor, tudo. Quem decide é o service (`reports/service.resolve`), como na
API: a tela não precisa de requires().

O período, os filtros e a aba ficam na URL, como na lista de chamados. Grupo, pessoa, cliente e
status aceitam vários valores (o parâmetro repetido).
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import partial
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from chamados.db.session import DB
from chamados.modules.reports import router as reports_api
from chamados.modules.reports import service
from chamados.modules.reports.schemas import DayRow, Report
from chamados.web.formatting import TIMEZONE, format_day, format_month, format_number
from chamados.web.page import LoggedPage, LoggedPageDep

router = APIRouter()

# Slug da aba na URL → chave do catálogo (relatorios.abas.*).
TABS = {"produtividade": "produtividade", "clientes": "clientes", "horas-extras": "horasExtras"}
# A tabela de cada aba no CSV (`reports/csv_export.Table`).
CSV_TABLES = {"produtividade": "people", "clientes": "clients", "horas-extras": "overtime"}
CUSTOM = "personalizado"
NO_CLIENT = "sem-cliente"
# Períodos que andam com o calendário: slug → chave do catálogo (relatorios.periodos.*).
RELATIVE = {
    "mes-atual": "mesAtual",
    "mes-anterior": "mesAnterior",
    "ultimos-7-dias": "ultimos7",
    "ultimos-30-dias": "ultimos30",
    "ultimos-90-dias": "ultimos90",
    "trimestre-atual": "trimestreAtual",
    "trimestre-anterior": "trimestreAnterior",
    "ano-ate-hoje": "anoAteHoje",
}
Values = Annotated[list[str] | None, Query()]
WEEKDAYS = ("seg", "ter", "qua", "qui", "sex", "sab", "dom")


@dataclass
class Month:
    value: str  # "2026-10"
    label: str
    start: date
    end: date


@dataclass
class Point:
    """Uma coluna ou barra dos gráficos (templates/reports/_charts.html)."""

    key: str
    label: str
    value: int


def _months(locale: str, today: date) -> list[Month]:
    """Os 12 últimos meses, o atual primeiro."""
    months = []
    first = today.replace(day=1)
    for _ in range(12):
        last = (first + timedelta(days=31)).replace(day=1) - timedelta(days=1)
        months.append(Month(f"{first:%Y-%m}", format_month(locale, first), first, last))
        first = (first - timedelta(days=1)).replace(day=1)
    return months


def _quarter(day: date) -> tuple[date, date]:
    first = date(day.year, (day.month - 1) // 3 * 3 + 1, 1)
    after = date(first.year + (first.month == 10), (first.month + 2) % 12 + 1, 1)
    return first, after - timedelta(days=1)


def _relative(slug: str, today: date, months: list[Month]) -> tuple[date, date]:
    """O início e o fim (incluído) de um período de RELATIVE. O mês e o trimestre vão até o
    último dia, como os meses da lista; os demais terminam hoje."""
    if slug == "mes-atual":
        return months[0].start, months[0].end
    if slug == "mes-anterior":
        return months[1].start, months[1].end
    if slug == "trimestre-atual":
        return _quarter(today)
    if slug == "trimestre-anterior":
        return _quarter(_quarter(today)[0] - timedelta(days=1))
    if slug == "ano-ate-hoje":
        return today.replace(month=1, day=1), today
    days = {"ultimos-7-dias": 7, "ultimos-30-dias": 30, "ultimos-90-dias": 90}[slug]
    return today - timedelta(days=days - 1), today


def _date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _uuids(values: list[str] | None) -> list[uuid.UUID]:
    """Os valores que são UUID, sem repetir; o resto (ex.: "sem-cliente") fica de fora."""
    result = []
    for value in values or []:
        try:
            parsed = uuid.UUID(value)
        except ValueError:
            continue
        if parsed not in result:
            result.append(parsed)
    return result


def _series(locale: str, days: list[DayRow], field: str) -> list[Point]:
    """Até dois meses, uma coluna por dia; mais que isso, por semana (a partir do primeiro dia)."""
    size = 7 if len(days) > 62 else 1
    return [
        Point(
            days[i].date.isoformat(),
            format_day(locale, days[i].date),
            sum(getattr(d, field) for d in days[i : i + size]),
        )
        for i in range(0, len(days), size)
    ]


def _charts(page: LoggedPage, report: Report) -> dict[str, Any]:
    """Os números dos gráficos e das tabelas, como o ReportsView.vue os montava."""
    locale = page.locale
    no_client = page.t("relatorios.semCliente")
    clients = [
        Point(str(c.id) if c.id else "sem-cliente", c.name or no_client, c.minutes)
        for c in report.clients
    ]
    wh = report.work_hours
    return {
        "by_day": _series(locale, report.days, "minutes"),
        "overtime_by_day": _series(locale, report.days, "overtime_minutes"),
        "weekly": len(report.days) > 62,
        "people_bars": [Point(str(p.id), p.name, p.minutes) for p in report.people],
        "overtime_bars": [
            Point(str(p.id), p.name, p.overtime_minutes)
            for p in sorted(report.people, key=lambda p: -p.overtime_minutes)
            if p.overtime_minutes > 0
        ],
        "client_bars": [c for c in clients if c.value > 0][:10],
        "client_names": [c.label for c in clients],
        "work_hours": page.t(
            "relatorios.expedienteUsado",
            dias=", ".join(page.t(f"expediente.diasCurtos.{WEEKDAYS[d]}") for d in wh.weekdays),
            inicio=f"{wh.start:%H:%M}",
            fim=f"{wh.end:%H:%M}",
        ),
    }


@router.get("/relatorios")
async def reports_page(
    page: LoggedPageDep,
    db: DB,
    aba: str | None = None,
    periodo: str | None = None,
    de: str | None = None,
    ate: str | None = None,
    grupo: Values = None,
    pessoa: Values = None,
    cliente: Values = None,
    status: Values = None,
) -> HTMLResponse:
    auth = page.auth
    today = datetime.now(TIMEZONE).date()
    months = _months(page.locale, today)
    tab = aba if aba in TABS else "produtividade"

    # Um período relativo, um mês da lista ou o personalizado; sem período (ou um desconhecido),
    # o mês atual. Ao escolher "Personalizado", as datas começam no primeiro dia do mês e em
    # hoje; uma data apagada é um período inválido.
    month = next((m for m in months if m.value == periodo), None)
    period = periodo if periodo in RELATIVE or periodo == CUSTOM or month else "mes-atual"
    if period in RELATIVE:
        first, last = _relative(period, today, months)
        start_text, end_text = first.isoformat(), last.isoformat()
    elif month:
        start_text, end_text = month.start.isoformat(), month.end.isoformat()
    else:
        start_text = months[0].start.isoformat() if de is None else de
        end_text = today.isoformat() if ate is None else ate
    start, end = _date(start_text), _date(end_text)

    teams = _uuids(grupo)
    people = _uuids(pessoa)
    clients = _uuids(cliente)
    no_client = NO_CLIENT in (cliente or [])
    statuses = [int(v) for v in status or [] if v.isdigit()]
    options = await reports_api.report_options(auth, db)
    report: Report | None = None
    error = None
    if start and end and start <= end:
        try:
            f = await service.resolve(
                db,
                auth,
                start=start,
                end=end,
                teams=teams,
                people=people,
                clients=clients,
                no_client=no_client,
                statuses=statuses,
            )
            report = await reports_api.report(f, auth, db)
        except HTTPException as exc:
            error = page.api_message(exc)

    query: dict[str, str | list[str] | None] = {
        "periodo": period,
        "de": start_text if period == CUSTOM else None,
        "ate": end_text if period == CUSTOM else None,
        "grupo": [str(t) for t in teams],
        "pessoa": [str(p) for p in people],
        "cliente": ([NO_CLIENT] if no_client else []) + [str(c) for c in clients],
        "status": [str(s) for s in statuses],
    }

    def tab_url(slug: str) -> str:
        params = {k: v for k, v in {**query, "aba": slug}.items() if v}
        return f"/relatorios?{urlencode(params, doseq=True)}"

    # Os downloads levam os mesmos filtros à API, com o idioma da pessoa (um link não escolhe o
    # Accept-Language).
    downloads = None
    if report is not None:
        api = {
            "start": report.start.isoformat(),
            "end": report.end.isoformat(),
            "team": query["grupo"],
            "person": query["pessoa"],
            "client": [str(c) for c in clients],
            "no_client": "true" if no_client else None,
            "status": query["status"],
            "locale": page.locale,
        }

        def api_url(path: str, **extra: str) -> str:
            params = {k: v for k, v in {**api, **extra}.items() if v}
            return f"/api/v1/reports/{path}?{urlencode(params, doseq=True)}"

        downloads = {
            "pdf": api_url("pdf"),
            "csv": api_url("csv", table=CSV_TABLES[tab]),
            "tarefas": api_url("csv", table="tasks"),
        }

    # Os filtros de vários valores (etiquetas): nome, rótulo, opções, escolhidos e o texto de
    # "todos". Grupo só com o que escolher; pessoa, só para quem vê mais que o próprio trabalho.
    filters = []
    if options.teams:
        team_options = [(str(t.id), t.name) for t in options.teams]
        filters.append(("grupo", "grupo", team_options, query["grupo"], "todosOsGrupos"))
    if len(options.people) > 1:
        person_options = [(str(p.id), p.name) for p in options.people]
        filters.append(("pessoa", "pessoa", person_options, query["pessoa"], "todasAsPessoas"))
    client_options = [(NO_CLIENT, page.t("relatorios.semCliente"))]
    client_options += [(str(c.id), c.name) for c in options.clients]
    filters.append(("cliente", "cliente", client_options, query["cliente"], "todosOsClientes"))
    status_options = [(str(s.id), s.name) for s in options.statuses]
    filters.append(("status", "status", status_options, query["status"], "todosOsStatus"))

    return page.render(
        "reports/index.html",
        tabs=TABS,
        tab=tab,
        tab_url=tab_url,
        period=period,
        period_groups=[
            (
                page.t("relatorios.periodosRelativos"),
                [(slug, page.t(f"relatorios.periodos.{key}")) for slug, key in RELATIVE.items()],
            ),
            (page.t("relatorios.meses"), [(m.value, m.label) for m in months]),
        ],
        start=start_text,
        end=end_text,
        period_ok=bool(start and end and start <= end),
        # O intervalo de um período relativo ou de um mês, que não aparece nos campos de data.
        interval=page.t(
            "relatorios.intervalo",
            de=format_day(page.locale, start),
            ate=format_day(page.locale, end),
        )
        if start and end and period != CUSTOM
        else None,
        filters=filters,
        report=report,
        error=error,
        downloads=downloads,
        number=partial(format_number, page.locale),
        **(_charts(page, report) if report else {}),
    )
