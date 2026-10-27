"""Relatórios: cada bloco de um modelo pronto para o template e para o PDF (docs/14 §14.8.3):
os números calculados (`reports/builder.run`) e já formatados, os títulos automáticos, a
variação sobre o período comparado e os links de detalhar; e a prévia do relatório para o
cliente (§14.8.5).
"""

import math
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from functools import partial
from typing import Any

from fastapi import HTTPException

from chamados.db.session import DB
from chamados.modules.reports import builder, service
from chamados.modules.reports.builder import (
    CATEGORIES,
    CHARTS,
    CUSTOM,
    CYCLES,
    DEFAULT_DAYS,
    DURATIONS,
    ELAPSED,
    GOOD_DIRECTION,
    LAST_DAYS,
    OTHERS,
    PERCENT,
    RATES,
    TICKET_SETS,
    TIMES,
    Block,
    FilterSpec,
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
from chamados.web.reports_state import NO_CLIENT, RELATIVE_KEYS, State, origin_of, with_query

DAILY_LIMIT = 62  # um gráfico por dia de um período mais longo agrupa por semana


# As colunas da lista de tarefas → chave do catálogo (relatorios.colunas.*).
TASK_COLUMN_KEYS: dict[builder.TaskColumn, str] = {
    "when": "quando",
    "person": "pessoa",
    "ticket": "chamado",
    "client": "cliente",
    "team": "grupo",
    "status": "status",
    "time": "tempo",
    "overtime": "foraDoExpediente",
}

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


# Os campos do filtro → chave do catálogo (relatorios.*): o subtítulo e os avisos de um bloco.
FILTER_LABELS: dict[builder.FilterField, str] = {
    "teams": "grupo",
    "people": "pessoa",
    "clients": "cliente",
    "statuses": "status",
}


@dataclass
class Scope:
    """O período e os filtros com que um bloco é calculado: os da tela ou os próprios dele
    (`Block.period`, `Block.filters`), e os dados lidos para eles."""

    filters: service.Filters | None  # None: o bloco não consulta nada (`message`)
    query: dict[str, Any]  # os mesmos na URL: o detalhar e a lista de chamados
    origin: str  # o período como origem do detalhar (`origin_of`)
    comparison: tuple[date, date] | None = None
    period: str = ""  # o nome do período próprio, para o subtítulo
    filtered: str = ""  # o filtro próprio, para o subtítulo
    message: str | None = None  # o filtro do bloco não combina com o da tela (ou o erro)
    warning: str | None = None  # partes do filtro do bloco que deixaram de valer
    data: service.Facts | None = None
    before: service.Facts | None = None  # o período comparado


async def scopes(
    page: LoggedPage, db: DB, state: State, blocks: Sequence[Block], *, compare: bool = True
) -> list[Scope]:
    """O período, os filtros e os dados de cada bloco. Os blocos com o mesmo período e os mesmos
    filtros efetivos formam um grupo, e o `facts` vem uma vez por grupo, com as partes de todos
    eles juntas (`builder.needs`); o do período comparado também, só com os blocos que comparam
    (`compare`: a prévia do editor não compara). O filtro do bloco passa pelo `resolve`, como o
    da tela, e o que saiu do alcance da pessoa fica de fora, com o aviso."""
    f = state.filters
    if f is None:
        raise ValueError("scopes sem o período e os filtros da tela (veja o state.error)")
    today = datetime.now(TIMEZONE).date()
    screen = state.specs()[1]
    o = state.options
    teams = {t.id: t.name for t in o.teams}
    people = {p.id: p.name for p in o.people}
    statuses = {s.id: s.name for s in o.statuses}
    clients = await service.client_labels(
        db, {c for b in blocks if b.filters for c in b.filters.clients}
    )
    # Cada grupo: o período, os filtros efetivos e se é o "ano até hoje" (a comparação muda).
    groups: dict[tuple[date, date, bool, str], list[int]] = {}
    found: list[Scope] = []
    specs: list[FilterSpec] = []
    for i, block in enumerate(blocks):
        scope = Scope(filters=None, query={**state.query}, origin=origin_of(state))
        start, end = f.start, f.end
        year_to_date = state.period == "ano-ate-hoje"
        if block.period is not None:
            kind = block.period.kind
            days = (block.period.days or DEFAULT_DAYS) if kind == LAST_DAYS else None
            start, end = builder.relative_period(kind, today, days)
            year_to_date = kind == "ano-ate-hoje"
            scope.origin = f"{LAST_DAYS}:{days}" if days else kind
            scope.query.update(periodo=kind, de=None, ate=None, dias=days and str(days))
            scope.query["origem"] = None
            scope.period = (
                page.t("relatorios.periodos.ultimosNDias", n=days)
                if days
                else page.t(f"relatorios.periodos.{RELATIVE_KEYS[kind]}")
            )
        spec = screen
        if block.filters is not None:
            own = block.filters
            kept = FilterSpec(
                teams=[t for t in own.teams if t in teams],
                people=[p for p in own.people if p in people],
                clients=[c for c in own.clients if c in clients],
                no_client=own.no_client,
                statuses=[s for s in own.statuses if s in statuses],
            )
            names = {
                "teams": [teams[t] for t in kept.teams],
                "people": [people[p] for p in kept.people],
                "clients": [page.t("relatorios.semCliente")] * kept.no_client
                + [clients[c] for c in kept.clients],
                "statuses": [statuses[s] for s in kept.statuses],
            }
            described = {
                field: f"{page.t(f'relatorios.{label}')}: {', '.join(names[field])}"
                for field, label in FILTER_LABELS.items()
                if names[field]
            }
            scope.filtered = " · ".join(described.values())
            lost = [
                page.t(f"relatorios.{label}")
                for field, label in FILTER_LABELS.items()
                if len(getattr(kept, field)) < len(getattr(own, field))
            ]
            if lost:
                scope.warning = page.t("relatorios.filtroDoBlocoInvalido", filtros=", ".join(lost))
            spec, conflicts = builder.narrow(screen, kept)
            if conflicts:
                scope.message = page.t(
                    "relatorios.filtroNaoCombina", filtro="; ".join(described[c] for c in conflicts)
                )
            scope.query.update(
                grupo=[str(t) for t in spec.teams],
                pessoa=[str(p) for p in spec.people],
                cliente=[NO_CLIENT] * spec.no_client + [str(c) for c in spec.clients],
                status=[str(s) for s in spec.statuses],
            )
        try:
            scope.comparison = builder.comparison_period(
                start, end, state.compare, year_to_date=year_to_date
            )
        except ValueError:  # antes do ano 1: não há com que comparar
            scope.comparison = None
        found.append(scope)
        specs.append(spec)
        if scope.message is None:
            key = (start, end, year_to_date, spec.model_dump_json())
            groups.setdefault(key, []).append(i)

    for (start, end, _, _), members in groups.items():
        spec = specs[members[0]]
        filters = f
        if spec != screen or (start, end) != (f.start, f.end):
            try:
                filters = await service.resolve(
                    db,
                    page.auth,
                    start=start,
                    end=end,
                    teams=spec.teams,
                    people=spec.people,
                    clients=spec.clients,
                    no_client=spec.no_client,
                    statuses=spec.statuses,
                )
            except HTTPException as exc:
                for i in members:
                    found[i].message = page.api_message(exc)
                continue
        group = [blocks[i] for i in members]
        data = await service.facts(db, page.auth, filters, builder.needs(group), state.lookups)
        before = None
        compared_period = found[members[0]].comparison
        compared_blocks = [b for b in group if b.visual in COMPARED]
        if compare and compared_period and compared_blocks:
            first, last = compared_period
            before = await service.facts(
                db,
                page.auth,
                replace(filters, start=first, end=last),
                builder.needs(compared_blocks),
                state.lookups,
            )
        for i in members:
            found[i].filters, found[i].data, found[i].before = filters, data, before
    return found


def wide(visuals: Sequence[str], widths: Sequence[str | None] = ()) -> list[bool]:
    """Quais blocos ocupam a linha inteira da grade (os gráficos ocupam meia): os que não são
    gráficos e o último de uma sequência ímpar de gráficos, que ficaria sozinho com a outra
    metade vazia. Um seletor CSS não conta a sequência entre dois blocos de linha inteira.
    `widths`: a largura escolhida em cada bloco (`Block.width`), que vale mais que a regra: um
    de meia linha conta na sequência, mas não cresce."""
    chosen = [*widths, *[None] * (len(visuals) - len(widths))]
    half = [
        w == "half" or (w is None and v in CHARTS) for v, w in zip(visuals, chosen, strict=True)
    ]
    result = []
    run = 0  # os blocos de meia linha seguidos até aqui
    for i, width in enumerate(chosen):
        if not half[i]:
            run = 0
            result.append(True)
            continue
        run += 1
        last = i + 1 == len(visuals) or not half[i + 1]
        result.append(width is None and last and run % 2 == 1)
    return result


Format = Callable[[builder.Value], str]


def formatter(
    page: LoggedPage, config: ReportConfig, measure: str, block: Block | None = None
) -> Format:
    """Como mostrar os valores de uma medida; sem base (mediana de nada), um travessão. O bloco
    pode trocar o formato das horas do modelo e as casas decimais (`Block.hours`,
    `Block.decimals`)."""
    places = block.decimals if block else None
    if measure in DURATIONS:
        hours = (block.hours if block else None) or config.hours
        base: Callable[[int], str] = (
            format_duration
            if hours == "hm"
            else partial(format_hours, page.locale, decimals=places)
        )
    elif measure in ELAPSED:
        base = format_elapsed
    elif measure in PERCENT:
        base = partial(format_percent, page.locale, decimals=places)
    elif measure in RATES:
        base = partial(format_tenths, page.locale, decimals=places)
    else:
        base = partial(format_number, page.locale)
    return lambda value: "—" if value is None else base(value)


def _step(measure: str, highest: int, decimals: int | None = None) -> int:
    """O passo do eixo dos gráficos (_charts.html): horas cheias e pares, dias, 20% ou 2. As
    marcas são o topo e a metade: sem casas decimais, a metade de uma taxa precisa ser inteira."""
    if measure in DURATIONS:
        return 120
    if measure in ELAPSED:
        return 1440 if highest > 2880 else 120
    if measure in RATES:
        return 200 if decimals == 0 else 100  # 1 por dia
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
    elif block.visual == "combo":
        title = page.t(
            "relatorios.tituloCombo",
            primeira=measure_label(page, block, block.measures[0]),
            segunda=measure_label(page, block, block.measures[-1]).lower(),
            dimensao=what,
        )
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
    state: State, scope: Scope, dimension: str | None, key: builder.Key
) -> dict[str, Any] | None:
    """Os filtros que uma linha (ou barra, coluna) aplica ao ser clicada; None: não aplica (os
    "Outros", as idades, alguém que a pessoa não pode filtrar). Um período clicado leva o de
    agora (o do bloco) como `origem`, para a tela mostrar a trilha e voltar a ele."""
    f, data = scope.filters, scope.data
    if f is None or data is None or key == OTHERS or dimension in (None, "age", *CYCLES):
        return None
    if isinstance(key, date):
        first = max(key, f.start)
        last = min(builder.bucket_end(key, dimension), f.end)  # type: ignore[arg-type]
        return {
            "periodo": CUSTOM,
            "de": first.isoformat(),
            "ate": last.isoformat(),
            "dias": None,
            "origem": scope.origin,
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
    config: ReportConfig,
    block: Block,
    index: int,
    scope: Scope,
    page_number: int = 1,
) -> dict[str, Any]:
    """Um bloco pronto para o template: os números já formatados e os links de detalhar.
    `scope`: o período, os filtros e os dados do bloco (`scopes`), com os do período comparado
    para a variação (cartões e tabelas) e a série de antes (colunas e linha por período);
    `page_number`: a página da lista de tarefas."""
    # O CSV e as páginas da lista são da tela (a rota acha o bloco de novo); o detalhar e a
    # lista de chamados, do período e dos filtros do bloco.
    screen = {**state.query, "aba": state.choice.slug}
    base = {**scope.query, "aba": state.choice.slug}
    view: dict[str, Any] = {
        "index": index,
        "visual": block.visual,
        "csv": with_query("/relatorios/csv", {**screen, "bloco": str(index)}),
        "own": block.period is not None or block.filters is not None,
        "height": block.height,
        "color": block.color or "chart-1",
        "warning": scope.warning,
    }
    f, data, before = scope.filters, scope.data, scope.before
    if f is None or data is None:
        view.update(title=block_title(page, block, block.dimension), message=scope.message)
        view["period"] = " · ".join(p for p in (scope.period, scope.filtered) if p)
        return view
    long = (f.end - f.start).days >= DAILY_LIMIT
    weekly = (
        block.visual in ("columns", "stacked", "line", "combo")
        and block.dimension == "day"
        and long
    )
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
        # A lista diz se o número era a média (o título dela é o nome da medida).
        mean = "media" if block.aggregate == "mean" and measure in ELAPSED else None
        return with_query(
            "/relatorios/chamados",
            {**base, **(drill or {}), "medida": measure, "agregacao": mean},
        )

    # O em aberto agrupa pelo status do fim do período; o filtro de status é o atual.
    can_drill = not (dimension == "status" and "backlog" in block.measures)

    def drill_of(row: builder.Row) -> dict[str, Any] | None:
        return _drill(state, scope, dimension, row.key) if can_drill else None

    def apply(row: builder.Row) -> str | None:
        drill = drill_of(row)
        return with_query("/relatorios", {**base, **drill}) if drill else None

    view["title"] = block_title(page, block, dimension)
    # O subtítulo: o período (com o nome do próprio), quando o bloco mostra a comparação, o de
    # antes, e o filtro próprio.
    subtitle = [
        scope.period,
        page.t(
            "relatorios.intervalo",
            de=format_day(page.locale, f.start),
            ate=format_day(page.locale, f.end),
        ),
    ]
    if previous is not None and (block.visual in ("cards", "table") or dimension in ORDERED):
        subtitle.append(
            page.t(
                "relatorios.comparacao.com",
                de=format_day(page.locale, first),
                ate=format_day(page.locale, last),
            )
        )
    view["period"] = " · ".join(p for p in (*subtitle, scope.filtered) if p)
    if block.visual == "cards":
        cards = []
        # A tendência no período, por dia (por semana num período longo, como os gráficos).
        trend = builder.trend(data, block, f.start, f.end, "week" if long else "day")
        for m in block.measures:
            fmt = formatter(page, config, m, block)
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
        view["big"] = block.big
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
            fmt=formatter(page, config, "hours", block),
            step=120,
            labels=(page.t("relatorios.noExpediente"), page.t("relatorios.medidas.overtime")),
        )
    elif block.visual == "combo":
        # As colunas da primeira medida e a linha da segunda (`extra`), no mesmo eixo.
        bars, line = block.measures
        fmt = formatter(page, config, bars, block)
        labels = (measure_label(page, block, bars), measure_label(page, block, line))
        points = []
        for r in result.rows:
            point = Point(
                str(r.key),
                _row_label(page, dimension, r, short=True),
                r.values[bars] or 0,
                extra=r.values[line] or 0,
                href=apply(r),
            )
            point.before_tip = f"{labels[1]}: {fmt(r.values[line])}"
            points.append(point)
        highest = max((max(p.value, p.extra) for p in points), default=0)
        view.update(
            points=points, fmt=fmt, step=_step(bars, highest, block.decimals), labels=labels
        )
    elif block.visual in CHARTS:
        m = block.measures[0]
        # A série de antes, só agrupada por período, dia da semana ou hora: nos cadastros, a
        # mesma posição não é o mesmo valor.
        series = previous is not None and dimension in ORDERED
        fmt = formatter(page, config, m, block)
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
            step=_step(m, highest, block.decimals),
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
        view.update(_heatmap(page, config, block, result))
    elif block.visual == "table":
        formats = [formatter(page, config, m, block) for m in block.measures]
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
        # Sem "Outros", as linhas não somam o total, que continua sendo o do período inteiro.
        view["total_label"] = page.t(
            "relatorios.totalComTodos" if result.cut else "relatorios.total"
        )
    else:
        fmt = formatter(page, config, "hours", block)
        # Em páginas de LISTED (`pagina<i>` na URL); uma fora da faixa vai para a mais perto.
        count = len(result.tasks)
        pages = max(1, -(-count // LISTED))
        current = min(max(1, page_number), pages)
        offset = (current - 1) * LISTED

        def page_url(n: int) -> str | None:
            if not 1 <= n <= pages:
                return None
            return with_query("/relatorios", {**screen, f"pagina{index}": str(n)})

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

        def client_name(client_id: int | None) -> str:
            found = data.clients.get(client_id) if client_id else None
            return found.label if found else page.t("relatorios.semCliente")

        view.update(
            tasks=[
                {
                    "done_at": t.done_at,
                    "person": data.users[t.author_id].display_name,
                    "number": t.ticket_number,
                    "title": t.ticket_title,
                    "minutes": fmt(t.minutes),
                    "overtime": fmt(t.overtime),
                    "client": client_name(t.client_id),
                    "team": data.teams[t.team_id].name,
                    "status": data.statuses[t.status_id].name,
                }
                for t in result.tasks[offset : offset + LISTED]
            ],
            # As colunas escolhidas no bloco, na ordem fixa (`builder.TASK_COLUMNS`).
            columns=[
                (c, page.t(f"relatorios.colunas.{TASK_COLUMN_KEYS[c]}"))
                for c in (block.columns or builder.DEFAULT_COLUMNS)
            ],
            count=count,
            empty=page.t("relatorios.semExtras" if block.only_overtime else "relatorios.vazio"),
        )
    return view


def _heatmap(
    page: LoggedPage, config: ReportConfig, block: Block, result: builder.Result
) -> dict[str, Any]:
    """O mapa de calor: uma linha por dia da semana, uma célula por hora, cada uma no tom da
    escala (`heat-1` a `heat-5`, 0 sem nada) pelo primeiro limite que ela não passa; a legenda,
    os mesmos limites. Cada limite é a fração do maior valor arredondada para cima, e um limite
    igual ao anterior (poucos valores, ex.: até 2 tarefas por hora) fica sem tom."""
    measure = block.measures[0]
    fmt = formatter(page, config, measure, block)
    values = [r.values[measure] for r in result.rows]  # dia × 24 + hora
    top = max((v or 0 for v in values), default=0)
    bounds = [math.ceil(top * k / HEAT_STEPS) for k in range(1, HEAT_STEPS + 1)]

    def level(value: builder.Value) -> int:
        if not value:
            return 0
        return next(k for k, bound in enumerate(bounds, 1) if value <= bound)

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
        (k, page.t("relatorios.mapa.ate", valor=fmt(bound)))
        for k, bound in enumerate(bounds, 1)
        if k == 1 or bound != bounds[k - 2]
    ]
    return {
        "hours": [page.t("relatorios.hora", h=h) for h in range(24)],
        "days": days,
        "legend": legend if top else [],
        "legend_label": page.t("relatorios.mapa.legenda"),
        "weekday_label": page.t("relatorios.dimensoes.weekday").capitalize(),
        "empty": page.t("relatorios.semExtras" if measure == "overtime" else "relatorios.nada"),
    }


# As colunas do relatório para o cliente → chave do catálogo (relatorios.paraCliente.colunas.*).
CLIENT_COLUMN_KEYS = {
    "ticket": "chamado",
    "title": "titulo",
    "opened": "registrado",
    "closed": "concluido",
    "status": "status",
    "hours": "horas",
    "people": "atendeu",
}


def uses_overtime(blocks: Sequence[Block]) -> bool:
    return any("overtime" in b.measures or b.only_overtime for b in blocks)


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


def single_client(state: State) -> str | None:
    """O nome do cliente do relatório para o cliente: o filtro precisa ter um, e só um."""
    if len(state.clients) != 1 or state.no_client:
        return None
    return state.client_names.get(state.clients[0])


async def client_preview(
    page: LoggedPage, db: DB, state: State, f: service.Filters, config: ReportConfig
) -> dict[str, Any]:
    """O relatório para o cliente (§14.8.5), na tela e no PDF, com os mesmos textos e na mesma
    ordem: o título, as linhas do cabeçalho (o cliente e o período), a abertura, os totais, os
    chamados, as observações e o rodapé (quando foi gerado). `keys`: as colunas da lista."""
    client = single_client(state)
    if client is None:
        return {"ready": False, "message": page.t("relatorios.paraCliente.umCliente")}
    # Os totais e a lista: as tarefas, os registrados e os concluídos.
    data = await service.facts(
        db, page.auth, f, service.Want(rows={"tasks", "opened", "closed"}), state.lookups
    )
    tickets = await service.client_tickets(db, page.auth, data)
    hours = formatter(page, config, "hours")
    spec = config.client
    # As colunas escolhidas, na ordem fixa; as horas e quem atendeu, quando o modelo pede.
    columns: list[str] = [c for c in builder.CLIENT_COLUMNS if c in spec.columns]
    if spec.show_hours:
        columns.append("hours")
    if config.show_people:
        columns.append("people")
    rows = []
    for t in tickets:
        cells = {
            "ticket": f"#{t.number}",
            "title": t.title,
            "opened": format_date(page.locale, t.created_at),
            "closed": format_date(page.locale, t.closed_at) if t.closed_at else "—",
            "status": t.status,
            "hours": hours(t.minutes),
            "people": ", ".join(t.people),
        }
        rows.append([cells[c] for c in columns])
    locale = page.locale
    period = page.t(
        "relatorios.pdf.periodo", de=format_date(locale, f.start), ate=format_date(locale, f.end)
    )
    now = format_datetime(locale, datetime.now(TIMEZONE))
    totals = [
        (page.t("relatorios.medidas.opened"), format_number(page.locale, len(data.opened))),
        (page.t("relatorios.medidas.closed"), format_number(page.locale, len(data.closed))),
    ]
    if spec.show_hours:
        totals.insert(
            0, (page.t("relatorios.medidas.hours"), hours(sum(t.minutes for t in data.tasks)))
        )
    return {
        "ready": True,
        "client": client,
        "title": page.t("relatorios.paraCliente.titulo"),
        "lines": [client, period],
        "intro": spec.intro,
        "notes": spec.notes,
        "footer": page.t("relatorios.paraCliente.gerado", quando=now),
        "totals": totals,
        "keys": columns,
        "columns": [
            page.t(f"relatorios.paraCliente.colunas.{CLIENT_COLUMN_KEYS[c]}") for c in columns
        ],
        "rows": rows,
    }
