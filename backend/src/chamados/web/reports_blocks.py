"""Relatórios: cada bloco de um modelo pronto para o template e para o PDF (docs/14 §14.8.3):
os números calculados (`reports/builder.run`) e já formatados, os títulos automáticos, a
variação sobre o período comparado e os links de detalhar; e a prévia do relatório para o
cliente (§14.8.5).
"""

import math
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from functools import partial
from typing import Any

from chamados.db.session import DB
from chamados.modules.reports import builder, service
from chamados.modules.reports.builder import (
    CATEGORIES,
    CHARTS,
    CUSTOM,
    CYCLES,
    DURATIONS,
    ELAPSED,
    GOOD_DIRECTION,
    OTHERS,
    PERCENT,
    RATES,
    TICKET_SETS,
    TIMES,
    Block,
    ReportConfig,
)
from chamados.web.formatting import (
    TIMEZONE,
    format_date,
    format_datetime,
    format_day,
    format_duration,
    format_elapsed,
    format_hours,
    format_month,
    format_number,
    format_percent,
    format_tenths,
)
from chamados.web.page import LoggedPage
from chamados.web.palette import HEAT_STEPS
from chamados.web.reports_state import NO_CLIENT, State, origin_of, with_query

DAILY_LIMIT = 62  # um gráfico por dia de um período mais longo agrupa por semana


LISTED = 200  # tarefas por página na lista (e no PDF, só a primeira); o CSV traz todas

# Os dias da semana (0 = segunda) → chave dos catálogos (expediente.diasCurtos.*,
# relatorios.diasDaSemana.*).
WEEKDAYS = ("seg", "ter", "qua", "qui", "sex", "sab", "dom")
# Os agrupamentos em que cada chave tem o seu lugar fixo (todas aparecem, na ordem): a série de
# antes se alinha pela posição.
ORDERED = (*TIMES, *CYCLES)


@dataclass
class Point:
    """Uma coluna, barra ou ponto dos gráficos (templates/reports/_charts.html). `extra`: nas
    colunas empilhadas, a parte de cima (as horas extras, dentro de `value`); `href`: aplicar
    como filtro; `before`, `before_tip`: o valor do período comparado na mesma posição e a dica
    dele (comparar, nas colunas e na linha por período)."""

    key: str
    label: str
    value: int
    extra: int = 0
    href: str | None = None
    before: int | None = None
    before_tip: str = ""


# Os visuais que mostram o período comparado (comparar): os cartões, as tabelas (a coluna Δ) e,
# agrupados por período, as colunas e a linha.
COMPARED = ("cards", "table", "columns", "line")


def compared(config: ReportConfig) -> list[Block]:
    """Os blocos que precisam dos dados do período comparado (e só as partes deles vêm)."""
    return [b for b in config.blocks if b.visual in COMPARED]


def compares(config: ReportConfig) -> bool:
    """Se algum bloco precisa dos dados do período comparado."""
    return bool(compared(config))


def wide(visuals: Sequence[str]) -> list[bool]:
    """Quais blocos ocupam a linha inteira da grade (os gráficos ocupam meia): os que não são
    gráficos e o último de uma sequência ímpar de gráficos, que ficaria sozinho com a outra
    metade vazia. Um seletor CSS não conta a sequência entre dois blocos de linha inteira."""
    result = []
    run = 0  # os gráficos seguidos até aqui
    for i, visual in enumerate(visuals):
        if visual not in CHARTS:
            run = 0
            result.append(True)
            continue
        run += 1
        last = i + 1 == len(visuals) or visuals[i + 1] not in CHARTS
        result.append(last and run % 2 == 1)
    return result


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
    elif measure in RATES:
        base = partial(format_tenths, page.locale)
    else:
        base = partial(format_number, page.locale)
    return lambda value: "—" if value is None else base(value)


def _step(measure: str, highest: int) -> int:
    """O passo do eixo dos gráficos (_charts.html): horas cheias e pares, dias, 20% ou 2."""
    if measure in DURATIONS:
        return 120
    if measure in ELAPSED:
        return 1440 if highest > 2880 else 120
    if measure in RATES:
        return 100  # 1 por dia
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
    if dimension == "weekday" and isinstance(row.key, int):
        day = WEEKDAYS[row.key]
        return page.t(f"expediente.diasCurtos.{day}" if short else f"relatorios.diasDaSemana.{day}")
    if dimension == "hour":
        return page.t("relatorios.hora", h=row.key)
    return row.label or page.t("relatorios.semCliente")


def measure_label(page: LoggedPage, block: Block, measure: str) -> str:
    """O nome da medida no bloco: nos tempos até a conclusão, "Mediana…" ou "Média…"."""
    if block.aggregate == "mean" and measure in ELAPSED:
        return page.t(f"relatorios.medias.{measure}")
    return page.t(f"relatorios.medidas.{measure}")


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
        measure = measure_label(page, block, block.measures[0])
        title = page.t("relatorios.tituloAuto", medida=measure, dimensao=what)
    if block.top and dimension in CATEGORIES:
        title = page.t("relatorios.osMaiores", titulo=title, n=block.top)
    return title


def _change(page: LoggedPage, measure: str, now: builder.Value, before: builder.Value) -> str:
    """A variação sobre o período comparado (cartões e a coluna Δ das tabelas): em % (na
    reabertura, em pontos); sem base, vazia."""
    if now is None or before is None or (before == 0 and measure not in PERCENT):
        return ""
    if measure in PERCENT:
        diff = (now - before) / 100
        text = page.t("relatorios.comparacao.pontos", n=_signed(page, diff))
    else:
        text = f"{_signed(page, (now - before) / before * 100, decimals=0)}%"
    return text


def _trend(measure: builder.Measure, now: builder.Value, before: builder.Value) -> dict[str, str]:
    """A seta da variação de um cartão (`trend`: up ou down) e o tom (`tone`: good ou bad, pela
    GOOD_DIRECTION da medida; vazio nas neutras). Sem variação ou sem base, nada."""
    if now is None or before is None or now == before:
        return {}
    up = now > before
    good = GOOD_DIRECTION.get(measure)
    tone = "" if good is None else "good" if up == (good > 0) else "bad"
    return {"trend": "up" if up else "down", "tone": tone}


def _spark(values: list[builder.Value]) -> str | None:
    """Os pontos da sparkline de um cartão (`points` de um polyline num viewBox de 100 × 32), de
    zero ao maior valor; um dia sem base (a mediana de nada) fica sem ponto. Com menos de dois
    pontos, nada."""
    points = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(points) < 2:
        return None
    top = max(v for _, v in points) or 1
    step = 100 / (len(values) - 1)
    return " ".join(f"{i * step:.2f},{30 - v / top * 28:.2f}" for i, v in points)


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
    "Outros", as idades, alguém que a pessoa não pode filtrar). Um período clicado leva o de
    agora como `origem`, para a tela mostrar a trilha e voltar a ele."""
    f = state.filters
    if f is None or key == OTHERS or dimension in (None, "age", *CYCLES):
        return None
    if isinstance(key, date):
        first = max(key, f.start)
        last = min(builder.bucket_end(key, dimension), f.end)  # type: ignore[arg-type]
        return {
            "periodo": CUSTOM,
            "de": first.isoformat(),
            "ate": last.isoformat(),
            "dias": None,
            "origem": origin_of(state),
        }
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
    page_number: int = 1,
) -> dict[str, Any]:
    """Um bloco pronto para o template: os números já formatados e os links de detalhar.
    `before`: os dados do período comparado, para a variação (cartões e tabelas) e a série de
    antes (colunas e linha por período); `page_number`: a página da lista de tarefas."""
    base = {**state.query, "aba": state.choice.slug}
    long = (f.end - f.start).days >= DAILY_LIMIT
    weekly = block.visual in ("columns", "stacked", "line") and block.dimension == "day" and long
    result = builder.run(data, block, f.start, f.end, dimension="week" if weekly else None)
    dimension = result.dimension

    # O mesmo bloco no período comparado, agrupado do mesmo jeito.
    previous = None
    compared_period = state.comparison()
    if before is not None and compared_period and block.visual in COMPARED:
        first, last = compared_period
        previous = builder.run(before, block, first, last, dimension=dimension)

    def matching(index: int, row: builder.Row) -> builder.Row | None:
        return builder.matching(previous, index, row) if previous else None

    def tickets(measure: str, drill: dict[str, Any] | None = None) -> str | None:
        """A lista dos chamados por trás de um número (medidas de chamado)."""
        if measure not in TICKET_SETS:
            return None
        # A lista diz se o número era a média (o título dela é o nome da medida).
        mean = "media" if block.aggregate == "mean" and measure in ELAPSED else None
        return with_query(
            "/relatorios/chamados",
            {**base, **(drill or {}), "medida": measure, "agregacao": mean},
        )

    # O em aberto agrupa pelo status do fim do período; o filtro de status é o atual.
    can_drill = not (dimension == "status" and "backlog" in block.measures)

    def drill_of(row: builder.Row) -> dict[str, Any] | None:
        return _drill(state, data, dimension, row.key) if can_drill else None

    def apply(row: builder.Row) -> str | None:
        drill = drill_of(row)
        return with_query("/relatorios", {**base, **drill}) if drill else None

    view: dict[str, Any] = {
        "index": index,
        "visual": block.visual,
        "title": block_title(page, block, dimension),
        "csv": with_query("/relatorios/csv", {**base, "bloco": str(index)}),
    }
    # O subtítulo: o período e, quando o bloco mostra a comparação, o de antes.
    view["period"] = page.t(
        "relatorios.intervalo",
        de=format_day(page.locale, f.start),
        ate=format_day(page.locale, f.end),
    )
    if previous is not None and (block.visual in ("cards", "table") or dimension in ORDERED):
        view["period"] += " · " + page.t(
            "relatorios.comparacao.com",
            de=format_day(page.locale, first),
            ate=format_day(page.locale, last),
        )
    if block.visual == "cards":
        cards = []
        # A tendência no período, por dia (por semana num período longo, como os gráficos).
        trend = builder.trend(data, block, f.start, f.end, "week" if long else "day")
        for m in block.measures:
            fmt = formatter(page, config, m)
            card: dict[str, Any] = {
                "label": measure_label(page, block, m),
                "value": fmt(result.total[m]),
            }
            card["href"] = tickets(m)
            card["spark"] = _spark(trend[m]) if m in trend else None
            # A taxa de conclusão passa de 100% quando se conclui mais do que se registra.
            if m == "completion_rate" and (result.total[m] or 0) > 10000:
                card["hint"] = page.t("relatorios.acimaDe100")
            if previous is not None:
                card["change"] = _change(page, m, result.total[m], previous.total[m])
                card["before"] = fmt(previous.total[m])
                if card["change"]:
                    card.update(_trend(m, result.total[m], previous.total[m]))
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
        # A série de antes, só agrupada por período, dia da semana ou hora: nos cadastros, a
        # mesma posição não é o mesmo valor.
        series = previous is not None and dimension in ORDERED
        fmt = formatter(page, config, m)
        points = []
        for i, r in enumerate(result.rows):
            point = Point(
                str(r.key),
                _row_label(page, dimension, r, short=True),
                r.values[m] or 0,
                href=apply(r),
            )
            old = matching(i, r) if series else None
            if old is not None:
                point.before = old.values[m] or 0
                point.before_tip = page.t(
                    "relatorios.comparacao.dica",
                    rotulo=_row_label(page, dimension, old, short=True),
                    valor=fmt(point.before),
                )
            points.append(point)
        empty = "relatorios.semExtras" if m == "overtime" else "relatorios.nada"
        highest = max((max(p.value, p.before or 0) for p in points), default=0)
        view.update(
            points=[p for p in points if p.value] if block.visual == "bars" else points,
            fmt=fmt,
            step=_step(m, highest),
            empty=page.t(empty),
        )
        if series:
            view["legend"] = (
                page.t("relatorios.comparacao.atual"),
                page.t(f"relatorios.comparacao.legenda.{state.compare}"),
            )
        view["area"] = block.area
        # A linha de referência: a média ou a mediana dos pontos com valor (um ponto sem base,
        # como a mediana de nada, fica de fora).
        values = [v for r in result.rows if (v := r.values[m]) is not None]
        if block.reference != "none" and values:
            average = statistics.fmean if block.reference == "mean" else statistics.median
            reference = round(average(values))
            view["reference"] = (
                reference,
                page.t(f"relatorios.referencia.{block.reference}", valor=fmt(reference)),
            )
    elif block.visual == "heatmap":
        view.update(_heatmap(page, config, block.measures[0], result))
    elif block.visual == "table":
        formats = [formatter(page, config, m) for m in block.measures]
        names = [measure_label(page, block, m) for m in block.measures]
        rows = []
        for i, r in enumerate(result.rows):
            drill = drill_of(r)
            old = matching(i, r)
            cells: list[tuple[str, str | None]] = []
            for fmt, m in zip(formats, block.measures, strict=True):
                cells.append((fmt(r.values[m]), tickets(m, drill) if drill else None))
                if previous is not None:  # Δ: a variação sobre a linha de antes
                    change = _change(page, m, r.values[m], old.values[m]) if old else ""
                    cells.append((change, None))
            rows.append((_row_label(page, dimension, r, short=False), apply(r), cells))
        total: list[tuple[str, str | None]] = []
        for fmt, m in zip(formats, block.measures, strict=True):
            total.append((fmt(result.total[m]), tickets(m)))
            if previous is not None:
                total.append((_change(page, m, result.total[m], previous.total[m]), None))
        columns = [page.t(f"relatorios.dimensoes.{dimension}").capitalize()]
        # O nome de cada coluna para o leitor de tela (o Δ diz de qual medida é).
        titles: list[str | None] = [None]
        for name in names:
            columns.append(name)
            titles.append(None)
            if previous is not None:
                columns.append("Δ")
                titles.append(page.t("relatorios.comparacao.variacaoDe", medida=name))
        view.update(columns=columns, titles=titles, rows=rows, total=total)
    else:
        fmt = formatter(page, config, "hours")
        # Em páginas de LISTED (`pagina<i>` na URL); uma fora da faixa vai para a mais perto.
        count = len(result.tasks)
        pages = max(1, -(-count // LISTED))
        current = min(max(1, page_number), pages)
        offset = (current - 1) * LISTED

        def page_url(n: int) -> str | None:
            if not 1 <= n <= pages:
                return None
            return with_query("/relatorios", {**base, f"pagina{index}": str(n)})

        view.update(
            page=current,
            pages=pages,
            previous=page_url(current - 1),
            next=page_url(current + 1),
            showing=page.t(
                "relatorios.mostrando",
                de=format_number(page.locale, offset + 1),
                ate=format_number(page.locale, min(offset + LISTED, count)),
                total=format_number(page.locale, count),
            ),
        )
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
                for t in result.tasks[offset : offset + LISTED]
            ],
            count=count,
            empty=page.t("relatorios.semExtras" if block.only_overtime else "relatorios.vazio"),
        )
    return view


def _heatmap(
    page: LoggedPage, config: ReportConfig, measure: builder.Measure, result: builder.Result
) -> dict[str, Any]:
    """O mapa de calor: uma linha por dia da semana, uma célula por hora, cada uma no tom da
    escala (`heat-1` a `heat-5`, 0 sem nada) pela fração do maior valor; a legenda, o limite de
    cima de cada tom."""
    fmt = formatter(page, config, measure)
    values = [r.values[measure] for r in result.rows]  # dia × 24 + hora
    top = max((v or 0 for v in values), default=0)

    def level(value: builder.Value) -> int:
        return math.ceil(value / top * HEAT_STEPS) if value and top else 0

    days = []
    for weekday, key in enumerate(WEEKDAYS):
        name = page.t(f"relatorios.diasDaSemana.{key}")
        cells = []
        for hour in range(24):
            value = values[weekday * 24 + hour]
            when = f"{name}, {page.t('relatorios.hora', h=hour)}"
            cells.append({"label": when, "value": fmt(value), "level": level(value)})
        days.append((page.t(f"expediente.diasCurtos.{key}"), name, cells))
    legend = [(0, page.t("relatorios.mapa.nada"))]
    legend += [
        (k, page.t("relatorios.mapa.ate", valor=fmt(round(top * k / HEAT_STEPS))))
        for k in range(1, HEAT_STEPS + 1)
    ]
    return {
        "hours": [page.t("relatorios.hora", h=h) for h in range(24)],
        "days": days,
        "legend": legend if top else [],
        "legend_label": page.t("relatorios.mapa.legenda"),
        "weekday_label": page.t("relatorios.dimensoes.weekday").capitalize(),
        "empty": page.t("relatorios.semExtras" if measure == "overtime" else "relatorios.nada"),
    }


def uses_overtime(config: ReportConfig) -> bool:
    return any("overtime" in b.measures or b.only_overtime for b in config.blocks)


def single_client(state: State) -> str | None:
    """O nome do cliente do relatório para o cliente: o filtro precisa ter um, e só um."""
    if len(state.clients) != 1 or state.no_client:
        return None
    return state.client_names.get(state.clients[0])


async def client_preview(
    page: LoggedPage, db: DB, state: State, f: service.Filters, config: ReportConfig
) -> dict[str, Any]:
    """O relatório para o cliente (§14.8.5), na tela e no PDF, com os mesmos textos e na mesma
    ordem: o título, as linhas do cabeçalho (o cliente e o período), os totais, os chamados e o
    rodapé (quando foi gerado)."""
    client = single_client(state)
    if client is None:
        return {"ready": False, "message": page.t("relatorios.paraCliente.umCliente")}
    # Os totais e a lista: as tarefas, os registrados e os concluídos.
    data = await service.facts(
        db, page.auth, f, service.Want(rows={"tasks", "opened", "closed"}), state.lookups
    )
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
    locale = page.locale
    period = page.t(
        "relatorios.pdf.periodo", de=format_date(locale, f.start), ate=format_date(locale, f.end)
    )
    now = format_datetime(locale, datetime.now(TIMEZONE))
    return {
        "ready": True,
        "client": client,
        "title": page.t("relatorios.paraCliente.titulo"),
        "lines": [client, period],
        "footer": page.t("relatorios.paraCliente.gerado", quando=now),
        "totals": [
            (page.t("relatorios.medidas.hours"), hours(sum(t.minutes for t in data.tasks))),
            (page.t("relatorios.medidas.opened"), format_number(page.locale, len(data.opened))),
            (page.t("relatorios.medidas.closed"), format_number(page.locale, len(data.closed))),
        ],
        "columns": [page.t(f"relatorios.paraCliente.colunas.{c}") for c in columns],
        "rows": rows,
    }
