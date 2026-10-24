"""Relatórios: cada bloco de um modelo pronto para o template e para o PDF (docs/14 §14.8.3):
os números calculados (`reports/builder.run`) e já formatados, os títulos automáticos, a
variação sobre o período anterior e os links de detalhar; e a prévia do relatório para o
cliente (§14.8.5).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from functools import partial
from typing import Any

from chamados.db.session import DB
from chamados.modules.reports import builder, service
from chamados.modules.reports.builder import (
    CATEGORIES,
    CHARTS,
    CUSTOM,
    DURATIONS,
    ELAPSED,
    OTHERS,
    PERCENT,
    TICKET_SETS,
    Block,
    ReportConfig,
)
from chamados.web.formatting import (
    format_date,
    format_day,
    format_duration,
    format_elapsed,
    format_hours,
    format_month,
    format_number,
    format_percent,
)
from chamados.web.page import LoggedPage
from chamados.web.reports_state import NO_CLIENT, State, with_query

DAILY_LIMIT = 62  # um gráfico por dia de um período mais longo agrupa por semana


LISTED = 200  # tarefas mostradas na lista; o CSV traz todas


@dataclass
class Point:
    """Uma coluna, barra ou ponto dos gráficos (templates/reports/_charts.html). `extra`: nas
    colunas empilhadas, a parte de cima (as horas extras, dentro de `value`); `href`: aplicar
    como filtro."""

    key: str
    label: str
    value: int
    extra: int = 0
    href: str | None = None


Format = Callable[[builder.Value], str]


def formatter(page: LoggedPage, config: ReportConfig, measure: str) -> Format:
    """Como mostrar os valores de uma medida; sem base (mediana de nada), um travessão."""
    if measure in DURATIONS:
        base: Callable[[int], str] = (
            format_duration if config.hours == "hm" else partial(format_hours, page.locale)
        )
    elif measure in ELAPSED:
        base = format_elapsed
    elif measure in PERCENT:
        base = partial(format_percent, page.locale)
    else:
        base = partial(format_number, page.locale)
    return lambda value: "—" if value is None else base(value)


def _step(measure: str, highest: int) -> int:
    """O passo do eixo dos gráficos (_charts.html): horas cheias e pares, dias, 20% ou 2."""
    if measure in DURATIONS:
        return 120
    if measure in ELAPSED:
        return 1440 if highest > 2880 else 120
    return 2000 if measure in PERCENT else 2


def _row_label(page: LoggedPage, dimension: str | None, row: builder.Row, *, short: bool) -> str:
    if row.key == OTHERS:
        return page.t("relatorios.outros")
    if isinstance(row.key, date):
        if dimension == "month":
            return format_month(page.locale, row.key)
        day = format_day(page.locale, row.key)
        return page.t("relatorios.semanaDe", dia=day) if dimension == "week" and not short else day
    if dimension == "age":
        return page.t(f"relatorios.idades.{row.key}")
    return row.label or page.t("relatorios.semCliente")


def block_title(page: LoggedPage, block: Block, dimension: str | None) -> str:
    """O título digitado ou o automático (ex.: "Horas por pessoa")."""
    if block.title:
        return block.title
    if block.visual == "tasks":
        return page.t(
            "relatorios.tarefasForaDoExpediente" if block.only_overtime else "relatorios.tarefas"
        )
    if block.visual == "cards" or dimension is None:
        return ""
    what = page.t(f"relatorios.dimensoes.{dimension}")
    if block.visual == "table":
        title = page.t("relatorios.tituloTabela", dimensao=what)
    elif block.visual == "stacked":
        title = page.t("relatorios.tituloEmpilhado", dimensao=what)
    else:
        measure = page.t(f"relatorios.medidas.{block.measures[0]}")
        title = page.t("relatorios.tituloAuto", medida=measure, dimensao=what)
    if block.top and dimension in CATEGORIES:
        title = page.t("relatorios.osMaiores", titulo=title, n=block.top)
    return title


def _change(page: LoggedPage, measure: str, now: builder.Value, before: builder.Value) -> str:
    """A variação de um cartão sobre o período anterior: em % (na reabertura, em pontos)."""
    if now is None or before is None or (before == 0 and measure not in PERCENT):
        return ""
    if measure in PERCENT:
        diff = (now - before) / 100
        text = page.t("relatorios.comparacao.pontos", n=_signed(page, diff))
    else:
        text = f"{_signed(page, (now - before) / before * 100, decimals=0)}%"
    return text


def _signed(page: LoggedPage, number: float, *, decimals: int = 1) -> str:
    text = f"{abs(number):.{decimals}f}"
    if decimals:
        text = text.rstrip("0").rstrip(".")
    if page.locale != "en":
        text = text.replace(".", ",")
    if text in ("0", "0,0"):
        return "0"
    return ("+" if number > 0 else "−") + text


def _drill(
    state: State, data: service.Facts, dimension: str | None, key: builder.Key
) -> dict[str, Any] | None:
    """Os filtros que uma linha (ou barra, coluna) aplica ao ser clicada; None: não aplica (os
    "Outros", as idades, alguém que a pessoa não pode filtrar)."""
    f = state.filters
    if f is None or key == OTHERS or dimension in (None, "age"):
        return None
    if isinstance(key, date):
        first = max(key, f.start)
        last = min(builder.bucket_end(key, dimension), f.end)  # type: ignore[arg-type]
        return {"periodo": CUSTOM, "de": first.isoformat(), "ate": last.isoformat()}
    if dimension == "client":
        client = data.clients.get(key) if isinstance(key, int) else None
        return {"cliente": [str(client.public_id) if client else NO_CLIENT]}
    if dimension == "status":
        return {"status": [str(key)]}
    if not isinstance(key, int):
        return None
    if dimension == "person":
        person = data.users[key].public_id
        return {"pessoa": [str(person)]} if person in {p.id for p in state.options.people} else None
    team = data.teams[key].public_id
    return {"grupo": [str(team)]} if team in {t.id for t in state.options.teams} else None


def block_view(
    page: LoggedPage,
    state: State,
    f: service.Filters,
    config: ReportConfig,
    data: service.Facts,
    block: Block,
    index: int,
    before: service.Facts | None = None,
) -> dict[str, Any]:
    """Um bloco pronto para o template: os números já formatados e os links de detalhar.
    `before`: os dados do período anterior, para a variação dos cartões."""
    base = {**state.query, "aba": state.choice.slug}
    weekly = (
        block.visual in ("columns", "stacked", "line")
        and block.dimension == "day"
        and (f.end - f.start).days >= DAILY_LIMIT
    )
    result = builder.run(data, block, f.start, f.end, dimension="week" if weekly else None)
    dimension = result.dimension

    def tickets(measure: str, drill: dict[str, Any] | None = None) -> str | None:
        """A lista dos chamados por trás de um número (medidas de chamado)."""
        if measure not in TICKET_SETS:
            return None
        return with_query("/relatorios/chamados", {**base, **(drill or {}), "medida": measure})

    # O em aberto agrupa pelo status do fim do período; o filtro de status é o atual.
    can_drill = not (dimension == "status" and "backlog" in block.measures)

    def drill_of(row: builder.Row) -> dict[str, Any] | None:
        return _drill(state, data, dimension, row.key) if can_drill else None

    def apply(row: builder.Row) -> str | None:
        drill = drill_of(row)
        return with_query("/relatorios", {**base, **drill}) if drill else None

    view: dict[str, Any] = {
        "visual": block.visual,
        "title": block_title(page, block, dimension),
        "csv": with_query("/relatorios/csv", {**base, "bloco": str(index)}),
    }
    if block.visual == "cards":
        previous = None
        if before is not None:
            start, end = builder.previous_period(
                f.start, f.end, year_to_date=state.period == "ano-ate-hoje"
            )
            previous = builder.run(before, block, start, end).total
        cards = []
        for m in block.measures:
            fmt = formatter(page, config, m)
            card: dict[str, Any] = {
                "label": page.t(f"relatorios.medidas.{m}"),
                "value": fmt(result.total[m]),
            }
            card["href"] = tickets(m)
            if previous is not None:
                card["change"] = _change(page, m, result.total[m], previous[m])
                card["before"] = fmt(previous[m])
            cards.append(card)
        view["cards"] = cards
    elif block.visual == "stacked":
        points = [
            Point(
                str(r.key),
                _row_label(page, dimension, r, short=True),
                r.values["hours"] or 0,
                extra=r.values["overtime"] or 0,
                href=apply(r),
            )
            for r in result.rows
        ]
        view.update(
            points=points,
            fmt=formatter(page, config, "hours"),
            step=120,
            labels=(page.t("relatorios.noExpediente"), page.t("relatorios.medidas.overtime")),
        )
    elif block.visual in CHARTS:
        m = block.measures[0]
        points = [
            Point(
                str(r.key),
                _row_label(page, dimension, r, short=True),
                r.values[m] or 0,
                href=apply(r),
            )
            for r in result.rows
        ]
        empty = "relatorios.semExtras" if m == "overtime" else "relatorios.nada"
        view.update(
            points=[p for p in points if p.value] if block.visual == "bars" else points,
            fmt=formatter(page, config, m),
            step=_step(m, max((p.value for p in points), default=0)),
            empty=page.t(empty),
        )
    elif block.visual == "table":
        formats = [formatter(page, config, m) for m in block.measures]
        rows = []
        for r in result.rows:
            drill = drill_of(r)
            cells = [
                (fmt(r.values[m]), tickets(m, drill) if drill else None)
                for fmt, m in zip(formats, block.measures, strict=True)
            ]
            rows.append((_row_label(page, dimension, r, short=False), apply(r), cells))
        view.update(
            columns=[page.t(f"relatorios.dimensoes.{dimension}").capitalize()]
            + [page.t(f"relatorios.medidas.{m}") for m in block.measures],
            rows=rows,
            total=[
                (fmt(result.total[m]), tickets(m))
                for fmt, m in zip(formats, block.measures, strict=True)
            ],
        )
    else:
        fmt = formatter(page, config, "hours")
        view.update(
            tasks=[
                {
                    "done_at": t.done_at,
                    "person": data.users[t.author_id].display_name,
                    "number": t.ticket_number,
                    "title": t.ticket_title,
                    "minutes": fmt(t.minutes),
                    "overtime": fmt(t.overtime),
                }
                for t in result.tasks[:LISTED]
            ],
            count=len(result.tasks),
            empty=page.t("relatorios.semExtras" if block.only_overtime else "relatorios.vazio"),
        )
    return view


def uses_overtime(config: ReportConfig) -> bool:
    return any("overtime" in b.measures or b.only_overtime for b in config.blocks)


def _single_client(state: State) -> str | None:
    """O nome do cliente do relatório para o cliente: o filtro precisa ter um, e só um."""
    if len(state.clients) != 1 or state.no_client:
        return None
    return next((c.name for c in state.options.clients if c.id == state.clients[0]), None)


async def client_preview(
    page: LoggedPage, db: DB, state: State, f: service.Filters, config: ReportConfig
) -> dict[str, Any]:
    """O relatório para o cliente (§14.8.5), na tela e no PDF: os totais e os chamados."""
    client = _single_client(state)
    if client is None:
        return {"ready": False, "message": page.t("relatorios.paraCliente.umCliente")}
    data = await service.facts(db, page.auth, f)
    tickets = await service.client_tickets(db, page.auth, data)
    hours = formatter(page, config, "hours")
    columns = ["chamado", "titulo", "registrado", "concluido", "status", "horas"]
    if config.show_people:
        columns.append("atendeu")
    rows = []
    for t in tickets:
        row = [
            f"#{t.number}",
            t.title,
            format_date(page.locale, t.created_at),
            format_date(page.locale, t.closed_at) if t.closed_at else "—",
            t.status,
            hours(t.minutes),
        ]
        if config.show_people:
            row.append(", ".join(t.people))
        rows.append(row)
    return {
        "ready": True,
        "client": client,
        "totals": [
            (page.t("relatorios.medidas.hours"), hours(sum(t.minutes for t in data.tasks))),
            (page.t("relatorios.medidas.opened"), format_number(page.locale, len(data.opened))),
            (page.t("relatorios.medidas.closed"), format_number(page.locale, len(data.closed))),
        ],
        "columns": [page.t(f"relatorios.paraCliente.colunas.{c}") for c in columns],
        "rows": rows,
    }
