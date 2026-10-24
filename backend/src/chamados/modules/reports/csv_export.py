"""Relatório em CSV (docs/14 §14.8.4): uma tabela da tela, um bloco de um modelo ou todas as
tarefas do período, no idioma de quem pede. UTF-8 com BOM, para o Excel reconhecer a
codificação; em português, `;` e vírgula decimal, como o Excel em português espera. O tempo sai
em horas decimais (para somar na planilha) e em minutos.
"""

import csv
import io
from datetime import date, datetime
from typing import Literal

from chamados.core.i18n import Locale
from chamados.modules.reports.builder import DURATIONS, OTHERS, Measure, Result
from chamados.modules.reports.schemas import Report
from chamados.modules.reports.service import TZ, Facts

Table = Literal["people", "clients", "overtime", "tasks"]

# Nome do arquivo baixado, como o do PDF.
FILE_NAMES: dict[Table, str] = {
    "people": "pessoas",
    "clients": "clientes",
    "overtime": "horas-extras",
    "tasks": "tarefas",
}

TEXTS: dict[Locale, dict[str, str]] = {
    "pt-BR": {
        "person": "Pessoa",
        "client": "Cliente",
        "hours": "Horas",
        "overtime": "Horas extras",
        "tasks": "Tarefas",
        "opened": "Chamados registrados",
        "closed": "Chamados concluídos",
        "when": "Quando",
        "ticket": "Chamado",
        "title": "Título",
        "time": "Tempo",
        "outside": "Fora do expediente",
        "minutes": "{column} (min)",
        "no_client": "Sem cliente",
        "others": "Outros",
        "total": "Total",
        "team": "Grupo",
        "status": "Status",
        "day": "Dia",
        "week": "Semana",
        "month": "Mês",
    },
    "en": {
        "person": "Person",
        "client": "Client",
        "hours": "Hours",
        "overtime": "Overtime",
        "tasks": "Tasks",
        "opened": "Tickets opened",
        "closed": "Tickets closed",
        "when": "When",
        "ticket": "Ticket",
        "title": "Title",
        "time": "Time",
        "outside": "Outside working hours",
        "minutes": "{column} (min)",
        "no_client": "No client",
        "others": "Others",
        "total": "Total",
        "team": "Team",
        "status": "Status",
        "day": "Day",
        "week": "Week",
        "month": "Month",
    },
}

# Uma célula que começa assim vira fórmula no Excel (injeção de fórmula).
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _text(value: str) -> str:
    """Texto livre (título, nome): com cara de fórmula, ganha um apóstrofo na frente."""
    return f"'{value}" if value.startswith(FORMULA_START) else value


def render(report: Report, table: Table, locale: Locale) -> bytes:
    t = TEXTS[locale]
    pt = locale == "pt-BR"

    def time(key: str) -> list[str]:
        return [t[key], t["minutes"].format(column=t[key])]

    def hours(minutes: int) -> list[str | int]:
        decimal = f"{minutes / 60:.2f}"
        return [decimal.replace(".", ",") if pt else decimal, minutes]

    def when(moment: datetime) -> str:
        return moment.astimezone(TZ).strftime("%d/%m/%Y %H:%M" if pt else "%Y-%m-%d %H:%M")

    head: list[str]
    rows: list[list[str | int]]
    if table == "people":
        head = [t["person"], *time("hours"), *time("overtime"), t["tasks"], t["closed"]]
        rows = [
            [
                _text(p.name),
                *hours(p.minutes),
                *hours(p.overtime_minutes),
                p.tasks,
                p.tickets_closed,
            ]
            for p in report.people
        ]
    elif table == "clients":
        head = [t["client"], *time("hours"), t["opened"], t["closed"]]
        rows = [
            [_text(c.name or t["no_client"]), *hours(c.minutes), c.tickets_opened, c.tickets_closed]
            for c in report.clients
        ]
    else:
        head = [t["when"], t["person"], t["ticket"], t["title"], t["client"]]
        head += [*time("time"), *time("outside")]
        rows = [
            [
                when(r.done_at),
                _text(r.person),
                r.ticket_number,
                _text(r.ticket_title),
                _text(r.client or t["no_client"]),
                *hours(r.minutes),
                *hours(r.overtime_minutes),
            ]
            for r in (report.tasks if table == "tasks" else report.overtime_tasks)
        ]

    return _write(head, rows, pt)


def _write(head: list[str], rows: list[list[str | int]], pt: bool) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";" if pt else ",", lineterminator="\r\n")
    writer.writerow(head)
    writer.writerows(rows)
    return ("\ufeff" + buffer.getvalue()).encode()


def render_block(data: Facts, result: Result, locale: Locale) -> bytes:
    """Um bloco de um modelo: as linhas agrupadas, como na tela, com o total no fim (a coluna da
    medida tem o nome da do CSV das tabelas); a lista de tarefas, com as colunas do de tarefas."""
    t = TEXTS[locale]
    pt = locale == "pt-BR"

    def hours(minutes: int) -> list[str | int]:
        decimal = f"{minutes / 60:.2f}"
        return [decimal.replace(".", ",") if pt else decimal, minutes]

    rows: list[list[str | int]] = []
    if result.is_list:
        head = [t["when"], t["person"], t["ticket"], t["title"], t["client"]]
        head += [t["time"], t["minutes"].format(column=t["time"])]
        head += [t["outside"], t["minutes"].format(column=t["outside"])]
        for task in result.tasks:
            client = data.clients.get(task.client_id) if task.client_id else None
            rows.append(
                [
                    task.done_at.astimezone(TZ).strftime(
                        "%d/%m/%Y %H:%M" if pt else "%Y-%m-%d %H:%M"
                    ),
                    _text(data.users[task.author_id].display_name),
                    task.ticket_number,
                    _text(task.ticket_title),
                    _text(client.label if client else t["no_client"]),
                    *hours(task.minutes),
                    *hours(task.overtime),
                ]
            )
        return _write(head, rows, pt)

    measures = list(result.total)
    head = [t[result.dimension]] if result.dimension else []
    for m in measures:
        column = t[m]
        head += [column, t["minutes"].format(column=column)] if m in DURATIONS else [column]

    def values(v: dict[Measure, int]) -> list[str | int]:
        cells: list[str | int] = []
        for m in measures:
            cells += hours(v[m]) if m in DURATIONS else [v[m]]
        return cells

    if result.dimension == "month":
        day_format = "%m/%Y" if pt else "%Y-%m"
    else:
        day_format = "%d/%m/%Y" if pt else "%Y-%m-%d"
    for row in result.rows:
        if isinstance(row.key, date):
            label = row.key.strftime(day_format)
        elif row.key == OTHERS:
            label = t["others"]
        else:
            label = _text(row.label or t["no_client"])
        rows.append([label, *values(row.values)])
    rows.append([*([t["total"]] if result.dimension else []), *values(result.total)])
    return _write(head, rows, pt)
