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
from chamados.modules.reports.builder import (
    DURATIONS,
    ELAPSED,
    OTHERS,
    PERCENT,
    Measure,
    Result,
    Value,
)
from chamados.modules.reports.schemas import Report
from chamados.modules.reports.service import TZ, Facts, TicketFact

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
        "age": "Idade",
        "ages": "até 1 dia|1 a 3 dias|3 a 7 dias|mais de 7 dias",
        "canceled": "Chamados cancelados",
        "backlog": "Em aberto no fim",
        "lead_time": "Mediana até a conclusão",
        "net_lead_time": "Mediana até a conclusão, líquida",
        "reopen_rate": "Reabertura (%)",
        "people": "Responsáveis",
        "created": "Registrado em",
        "closed_at": "Concluído em",
        "canceled_at": "Cancelado em",
        "lead": "Tempo até a conclusão",
        "net_lead": "Tempo até a conclusão, líquido",
        "reopened": "Reaberto",
        "yes": "Sim",
        "no": "Não",
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
        "age": "Age",
        "ages": "up to 1 day|1 to 3 days|3 to 7 days|over 7 days",
        "canceled": "Tickets canceled",
        "backlog": "Open at the end",
        "lead_time": "Median time to close",
        "net_lead_time": "Median time to close, net",
        "reopen_rate": "Reopened (%)",
        "people": "Assignees",
        "created": "Opened at",
        "closed_at": "Closed at",
        "canceled_at": "Canceled at",
        "lead": "Time to close",
        "net_lead": "Time to close, net",
        "reopened": "Reopened",
        "yes": "Yes",
        "no": "No",
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
    timed = (*DURATIONS, *ELAPSED)  # em horas decimais e em minutos
    for m in measures:
        column = t[m]
        head += [column, t["minutes"].format(column=column)] if m in timed else [column]

    def values(v: dict[Measure, Value]) -> list[str | int]:
        cells: list[str | int] = []
        for m in measures:
            value = v[m]
            if value is None:  # mediana ou porcentagem sem nenhum chamado
                cells += ["", ""] if m in timed else [""]
            elif m in timed:
                cells += hours(value)
            elif m in PERCENT:
                percent = f"{value / 100:.1f}"
                cells.append(percent.replace(".", ",") if pt else percent)
            else:
                cells.append(value)
        return cells

    if result.dimension == "month":
        day_format = "%m/%Y" if pt else "%Y-%m"
    else:
        day_format = "%d/%m/%Y" if pt else "%Y-%m-%d"
    for row in result.rows:
        if isinstance(row.key, date):
            label = row.key.strftime(day_format)
        elif result.dimension == "age" and isinstance(row.key, int):
            label = t["ages"].split("|")[row.key]
        elif row.key == OTHERS:
            label = t["others"]
        else:
            label = _text(row.label or t["no_client"])
        rows.append([label, *values(row.values)])
    rows.append([*([t["total"]] if result.dimension else []), *values(result.total)])
    return _write(head, rows, pt)


def render_tickets(data: Facts, tickets: list[TicketFact], kind: str, locale: Locale) -> bytes:
    """Os chamados por trás de um número (detalhar): os de `kind` (opened, closed, canceled ou
    backlog), com as colunas de cada um (§14.5)."""
    t = TEXTS[locale]
    pt = locale == "pt-BR"
    moment = "%d/%m/%Y %H:%M" if pt else "%Y-%m-%d %H:%M"

    def hours(minutes: int | None) -> list[str | int]:
        if minutes is None:
            return ["", ""]
        decimal = f"{minutes / 60:.2f}"
        return [decimal.replace(".", ",") if pt else decimal, minutes]

    def timed(key: str) -> list[str]:
        return [t[key], t["minutes"].format(column=t[key])]

    head = [t["ticket"], t["title"], t["client"], t["team"], t["status"], t["people"]]
    head.append(t["created"])
    if kind == "closed":
        head += [t["closed_at"], *timed("lead"), *timed("net_lead"), t["reopened"]]
    elif kind == "canceled":
        head.append(t["canceled_at"])
    elif kind == "backlog":
        head += timed("age")
    rows: list[list[str | int]] = []
    for ticket in tickets:
        client = data.clients.get(ticket.client_id) if ticket.client_id else None
        people = sorted(data.users[u].display_name for u in ticket.people)
        row: list[str | int] = [
            ticket.number,
            _text(ticket.title),
            _text(client.label if client else t["no_client"]),
            _text(data.teams[ticket.team_id].name),
            _text(data.statuses[ticket.status_id].name),
            _text(", ".join(people)),
            ticket.created_at.astimezone(TZ).strftime(moment),
        ]
        finished = ticket.finished_at.astimezone(TZ).strftime(moment) if ticket.finished_at else ""
        if kind == "closed":
            row += [finished, *hours(ticket.lead), *hours(ticket.net_lead)]
            row.append(t["yes"] if ticket.reopened else t["no"])
        elif kind == "canceled":
            row.append(finished)
        elif kind == "backlog":
            row += hours(ticket.age)
        rows.append(row)
    return _write(head, rows, pt)
