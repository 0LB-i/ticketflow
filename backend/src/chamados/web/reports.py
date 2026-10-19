"""Relatórios (docs/14 §14.7): horas por pessoa, por cliente e por dia, horas extras e o PDF com
os mesmos filtros. Cada um vê o próprio trabalho; o supervisor, o dos grupos que supervisiona;
admin e auditor, tudo. Quem decide é o service (`reports/service.resolve`), como na API: a tela
não precisa de requires().

O período, os filtros e a aba ficam na URL, como na lista de chamados.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import partial
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException
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
CUSTOM = "personalizado"
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


def _date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


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
    grupo: str | None = None,
    pessoa: str | None = None,
    client_id: str | None = None,
    cliente_nome: str | None = None,
) -> HTMLResponse:
    auth = page.auth
    today = datetime.now(TIMEZONE).date()
    months = _months(page.locale, today)
    tab = aba if aba in TABS else "produtividade"

    # Um mês da lista ou o período personalizado. Ao escolher "Personalizado", as datas começam
    # no primeiro dia do mês e em hoje; uma data apagada é um período inválido.
    month = next((m for m in months if m.value == periodo), None)
    if periodo != CUSTOM and month is None:
        month = months[0]
    if month:
        start_text, end_text = month.start.isoformat(), month.end.isoformat()
    else:
        start_text = months[0].start.isoformat() if de is None else de
        end_text = today.isoformat() if ate is None else ate
    start, end = _date(start_text), _date(end_text)

    team, person, client = _uuid(grupo), _uuid(pessoa), _uuid(client_id)
    options = await reports_api.report_options(auth, db)
    report: Report | None = None
    error = None
    client_name = (cliente_nome or "").strip() if client else ""
    if start and end and start <= end:
        try:
            f = await service.resolve(
                db, auth, start=start, end=end, team=team, person=person, client=client
            )
            report = await reports_api.report(f, auth, db)
        except HTTPException as exc:
            error = page.api_message(exc)
        else:
            client_name = f.client.label if f.client else ""

    query = {
        "periodo": month.value if month else CUSTOM,
        "de": None if month else start_text,
        "ate": None if month else end_text,
        "grupo": str(team) if team else None,
        "pessoa": str(person) if person else None,
        "client_id": str(client) if client else None,
        "cliente_nome": client_name or None,
    }

    def tab_url(slug: str) -> str:
        params = {k: v for k, v in {**query, "aba": slug}.items() if v}
        return f"/relatorios?{urlencode(params)}"

    pdf_url = None
    if report is not None:
        pdf_params = {
            "start": report.start.isoformat(),
            "end": report.end.isoformat(),
            "team": query["grupo"],
            "person": query["pessoa"],
            "client": query["client_id"],
            "locale": page.locale,
        }
        pdf_url = "/api/v1/reports/pdf?" + urlencode({k: v for k, v in pdf_params.items() if v})

    return page.render(
        "reports/index.html",
        tabs=TABS,
        tab=tab,
        tab_url=tab_url,
        period=query["periodo"],
        period_options=[(m.value, m.label) for m in months]
        + [(CUSTOM, page.t("relatorios.personalizado"))],
        start=start_text,
        end=end_text,
        period_ok=bool(start and end and start <= end),
        team=query["grupo"] or "",
        team_options=[(str(t.id), t.name) for t in options.teams],
        person=query["pessoa"] or "",
        # Quem só vê o próprio trabalho não tem o que escolher em pessoa.
        person_options=[(str(p.id), p.name) for p in options.people]
        if len(options.people) > 1
        else [],
        client=query["client_id"] or "",
        client_name=client_name,
        report=report,
        error=error,
        pdf_url=pdf_url,
        number=partial(format_number, page.locale),
        **(_charts(page, report) if report else {}),
    )
