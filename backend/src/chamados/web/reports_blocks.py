"""Relatórios: cada bloco de uma aba pronto para o template e para o PDF (docs/14 §14.8.3): os
números calculados (`reports/builder.run`) e já formatados, os títulos automáticos, a variação
sobre o período comparado e os links de detalhar.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
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
    GOOD_DIRECTION,
    OTHERS,
    PERCENT,
    TICKET_SETS,
    TIMES,
    Block,
)
from chamados.web.formatting import (
    format_date,
    format_day,
    format_duration,
    format_elapsed,
    format_number,
    format_percent,
)
from chamados.web.page import LoggedPage
from chamados.web.reports_state import NO_CLIENT, State, origin_of, with_query

DAILY_LIMIT = 62  # um gráfico por dia de um período mais longo agrupa por semana


# As colunas da lista de tarefas → chave do catálogo (relatorios.colunas.*).
TASK_COLUMN_KEYS: dict[builder.TaskColumn, str] = {
    "when": "quando",
    "person": "pessoa",
    "ticket": "chamado",
    "client": "cliente",
    "time": "tempo",
    "overtime": "foraDoExpediente",
}

LISTED = 200  # tarefas por página na lista (e no PDF, só a primeira); o CSV traz todas


@dataclass
class Point:
    """Uma coluna, barra ou ponto dos gráficos (templates/reports/_charts.html). `href`: aplicar
    como filtro; `before`, `before_tip`: o valor do período comparado na mesma posição e a dica
    dele (comparar, nas colunas e na linha por período)."""

    key: str
    label: str
    value: int
    href: str | None = None
    before: int | None = None
    before_tip: str = ""


# Os visuais que mostram o período comparado (comparar): os cartões, as tabelas (a coluna Δ) e,
# agrupados por período, as colunas e a linha.
COMPARED = ("cards", "table", "columns", "line")


@dataclass
class Scope:
    """Os dados com que os blocos são calculados: os do período e os do período comparado."""

    filters: service.Filters
    data: service.Facts
    comparison: tuple[date, date] | None = None
    before: service.Facts | None = None  # o período comparado


async def scope(page: LoggedPage, db: DB, state: State, blocks: Sequence[Block]) -> Scope:
    """Os dados dos blocos: o `facts` vem uma vez, com as partes de todos eles juntas
    (`builder.needs`); o do período comparado também, só com os blocos que comparam."""
    f = state.filters
    if f is None:
        raise ValueError("scope sem o período e os filtros da tela (veja o state.error)")
    data = await service.facts(db, page.auth, f, builder.needs(blocks), state.lookups)
    found = Scope(filters=f, data=data, comparison=state.comparison())
    compared_blocks = [b for b in blocks if b.visual in COMPARED]
    if found.comparison and compared_blocks:
        first, last = found.comparison
        found.before = await service.facts(
            db,
            page.auth,
            replace(f, start=first, end=last, discount=0),  # o desconto é do período
            builder.needs(compared_blocks),
            state.lookups,
        )
    return found


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


def formatter(page: LoggedPage, measure: str) -> Format:
    """Como mostrar os valores de uma medida; sem base (mediana de nada), um travessão."""
    if measure in DURATIONS:
        base: Callable[[int], str] = format_duration
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
        day = format_day(page.locale, row.key)
        return page.t("relatorios.semanaDe", dia=day) if dimension == "week" and not short else day
    if dimension == "age":
        return page.t(f"relatorios.idades.{row.key}")
    return row.label or page.t("relatorios.semCliente")


def block_title(page: LoggedPage, block: Block, dimension: str | None) -> str:
    """O título automático (ex.: "Horas por pessoa")."""
    if block.visual == "tasks":
        return page.t(
            "relatorios.tarefasForaDoExpediente" if block.only_overtime else "relatorios.tarefas"
        )
    if block.visual == "cards" or dimension is None:
        return ""
    what = page.t(f"relatorios.dimensoes.{dimension}")
    if block.visual == "table":
        title = page.t("relatorios.tituloTabela", dimensao=what)
    else:
        measure = page.t(f"relatorios.medidas.{block.measures[0]}")
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
    state: State, scope: Scope, dimension: str | None, key: builder.Key
) -> dict[str, Any] | None:
    """Os filtros que uma linha (ou barra, coluna) aplica ao ser clicada; None: não aplica (os
    "Outros", as idades, alguém que a pessoa não pode filtrar). Um período clicado leva o de
    agora como `origem`, para a tela mostrar a trilha e voltar a ele."""
    f, data = scope.filters, scope.data
    if key == OTHERS or dimension in (None, "age"):
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
    block: Block,
    index: int,
    scope: Scope,
    page_number: int = 1,
) -> dict[str, Any]:
    """Um bloco pronto para o template: os números já formatados e os links de detalhar.
    `scope`: os dados (`scope`), com os do período comparado para a variação (cartões e tabelas)
    e a série de antes (colunas e linha por período); `page_number`: a página da lista de
    tarefas."""
    base = {**state.query, "aba": state.choice.slug}
    view: dict[str, Any] = {
        "index": index,
        "visual": block.visual,
        "csv": with_query("/relatorios/csv", {**base, "bloco": str(index)}),
    }
    f, data, before = scope.filters, scope.data, scope.before
    long = (f.end - f.start).days >= DAILY_LIMIT
    weekly = block.visual in ("columns", "line") and block.dimension == "day" and long
    result = builder.run(data, block, f.start, f.end, dimension="week" if weekly else None)
    dimension = result.dimension

    # O mesmo bloco no período comparado, agrupado do mesmo jeito.
    previous = None
    compared_period = scope.comparison
    if before is not None and compared_period and block.visual in COMPARED:
        first, last = compared_period
        previous = builder.run(before, block, first, last, dimension=dimension)

    def matching(index: int, row: builder.Row) -> builder.Row | None:
        return builder.matching(previous, index, row) if previous else None

    def tickets(measure: str, drill: dict[str, Any] | None = None) -> str | None:
        """A lista dos chamados por trás de um número (medidas de chamado)."""
        if measure not in TICKET_SETS:
            return None
        return with_query("/relatorios/chamados", {**base, **(drill or {}), "medida": measure})

    # O em aberto agrupa pelo status do fim do período; o filtro de status é o atual.
    can_drill = not (dimension == "status" and "backlog" in block.measures)

    def drill_of(row: builder.Row) -> dict[str, Any] | None:
        return _drill(state, scope, dimension, row.key) if can_drill else None

    def apply(row: builder.Row) -> str | None:
        drill = drill_of(row)
        return with_query("/relatorios", {**base, **drill}) if drill else None

    view["title"] = block_title(page, block, dimension)
    # O subtítulo: o período e, quando o bloco mostra a comparação, o de antes.
    subtitle = [
        page.t(
            "relatorios.intervalo",
            de=format_day(page.locale, f.start),
            ate=format_day(page.locale, f.end),
        )
    ]
    if previous is not None and (block.visual in ("cards", "table") or dimension in TIMES):
        subtitle.append(
            page.t(
                "relatorios.comparacao.com",
                de=format_day(page.locale, first),
                ate=format_day(page.locale, last),
            )
        )
    view["period"] = " · ".join(subtitle)
    if block.visual == "cards":
        cards = []
        # A tendência no período, por dia (por semana num período longo, como os gráficos).
        trend = builder.trend(data, block, f.start, f.end, "week" if long else "day")
        for m in block.measures:
            fmt = formatter(page, m)
            card: dict[str, Any] = {
                "label": page.t(f"relatorios.medidas.{m}"),
                "value": fmt(result.total[m]),
            }
            card["href"] = tickets(m)
            card["spark"] = _spark(trend[m]) if m in trend else None
            if previous is not None:
                card["change"] = _change(page, m, result.total[m], previous.total[m])
                card["before"] = fmt(previous.total[m])
                if card["change"]:
                    card.update(_trend(m, result.total[m], previous.total[m]))
            cards.append(card)
        view["cards"] = cards
    elif block.visual in CHARTS:
        m = block.measures[0]
        # A série de antes, só agrupada por período: nos cadastros, a mesma posição não é o
        # mesmo valor.
        series = previous is not None and dimension in TIMES
        fmt = formatter(page, m)
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
    elif block.visual == "table":
        formats = [formatter(page, m) for m in block.measures]
        names = [page.t(f"relatorios.medidas.{m}") for m in block.measures]
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
        view["total_label"] = page.t("relatorios.total")
    else:
        fmt = formatter(page, "hours")
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
            columns=[
                (c, page.t(f"relatorios.colunas.{TASK_COLUMN_KEYS[c]}"))
                for c in builder.DEFAULT_COLUMNS
            ],
            count=count,
            empty=page.t("relatorios.semExtras" if block.only_overtime else "relatorios.vazio"),
        )
    return view


def uses_overtime(blocks: Sequence[Block]) -> bool:
    return any({"overtime", "regular"} & set(b.measures) or b.only_overtime for b in blocks)


async def work_hours_line(page: LoggedPage, db: DB, state: State, f: service.Filters) -> str:
    """O expediente usado na hora extra (o cabeçalho do PDF, quando algum bloco a usa):
    o da instalação, os dos grupos e os próprios que valeram no período, só de quem a pessoa vê."""
    use = await service.schedule_use(db, page.auth, f, state.lookups.calendar)

    def t(key: str, **values: object) -> str:
        return page.t(f"relatorios.expedientes.{key}", **values)

    text = service.describe_use(
        use, t, t("dias").split("|"), lambda day: format_date(page.locale, day)
    )
    return page.t("relatorios.expedienteUsado", expediente=text)
