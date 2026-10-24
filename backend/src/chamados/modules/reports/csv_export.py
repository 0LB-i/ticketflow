"""Relatório em CSV (docs/14 §14.8.4): uma tabela da tela ou todas as tarefas do período, no
idioma de quem pede. UTF-8 com BOM, para o Excel reconhecer a codificação; em português, `;` e
vírgula decimal, como o Excel em português espera. O tempo sai em horas decimais (para somar na
planilha) e em minutos.
"""

import csv
import io
from datetime import datetime
from typing import Literal

from chamados.core.i18n import Locale
from chamados.modules.reports.schemas import Report
from chamados.modules.reports.service import TZ

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

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";" if pt else ",", lineterminator="\r\n")
    writer.writerow(head)
    writer.writerows(rows)
    return ("﻿" + buffer.getvalue()).encode()
