"""Relatórios (docs/14 §14.7 e §14.8): os modelos prontos (Produtividade, Clientes, Horas extras)
e os modelos pessoais, cada um uma lista de blocos do construtor guiado (`reports/builder.py`),
com o PDF e o CSV. Cada um vê o próprio trabalho; o supervisor, o dos grupos que supervisiona;
admin e auditor, tudo. Quem decide é o service (`reports/service.resolve`), como na API: a tela
não precisa de requires().

O modelo (`aba`), o período e os filtros ficam na URL, como na lista de chamados. Grupo, pessoa,
cliente e status aceitam vários valores (o parâmetro repetido). Sem nenhum filtro na URL, valem
os salvos no modelo; o formulário sempre manda o período, então mexer num filtro passa a valer o
da URL, e "Salvar filtros" o guarda no modelo.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from functools import partial
from typing import Annotated, Any, cast
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.datastructures import FormData

from chamados.core.i18n import Locale
from chamados.db.session import DB
from chamados.modules.reports import builder, csv_export, saved, service
from chamados.modules.reports import router as reports_api
from chamados.modules.reports.builder import (
    BUILTINS,
    CATEGORIES,
    CHARTS,
    CUSTOM,
    DURATIONS,
    ELAPSED,
    OTHERS,
    PERCENT,
    RELATIVE,
    STACKED,
    TICKET_SETS,
    TIMES,
    Block,
    FilterSpec,
    PeriodSpec,
    ReportConfig,
)
from chamados.modules.reports.models import ReportModel
from chamados.modules.reports.schemas import ReportOptions
from chamados.web.formatting import (
    TIMEZONE,
    format_day,
    format_duration,
    format_elapsed,
    format_hours,
    format_month,
    format_number,
    format_percent,
)
from chamados.web.page import LoggedPage, LoggedPageDep, check_csrf

router = APIRouter()

# Modelo pronto (slug da aba na URL) → chave do catálogo (relatorios.abas.*).
TABS = {
    "produtividade": "produtividade",
    "clientes": "clientes",
    "horas-extras": "horasExtras",
    "chamados": "chamados",
}
# A tabela de cada modelo pronto de horas no CSV da API (`reports/csv_export.Table`); esses
# também têm o PDF.
CSV_TABLES = {"produtividade": "people", "clientes": "clients", "horas-extras": "overtime"}
NO_CLIENT = "sem-cliente"
# Período relativo (slug) → chave do catálogo (relatorios.periodos.*).
RELATIVE_KEYS = dict(
    zip(
        RELATIVE,
        (
            "mesAtual",
            "mesAnterior",
            "ultimos7",
            "ultimos30",
            "ultimos90",
            "trimestreAtual",
            "trimestreAnterior",
            "anoAteHoje",
        ),
        strict=True,
    )
)
WEEKDAYS = ("seg", "ter", "qua", "qui", "sex", "sab", "dom")
DAILY_LIMIT = 62  # um gráfico por dia de um período mais longo agrupa por semana
LISTED = 200  # tarefas mostradas na lista; o CSV traz todas
Values = Annotated[list[str] | None, Query()]


@dataclass
class Params:
    """O modelo e os filtros como vêm na URL (ou num formulário, com os mesmos nomes); um ausente
    é None. Sem nenhum filtro, valem os salvos no modelo."""

    aba: str | None = None
    periodo: str | None = None
    de: str | None = None
    ate: str | None = None
    grupo: Values = None
    pessoa: Values = None
    cliente: Values = None
    status: Values = None
    comparar: str | None = None

    def hidden(self) -> list[tuple[str, str]]:
        """Os filtros em campos escondidos de um formulário."""
        fields = []
        for name in FILTER_FIELDS:
            value = getattr(self, name)
            fields += [(name, v) for v in ([value] if isinstance(value, str) else value or [])]
        return fields


ParamsDep = Annotated[Params, Depends()]
FILTER_FIELDS = ("periodo", "de", "ate", "grupo", "pessoa", "cliente", "status", "comparar")


@dataclass
class Month:
    value: str  # "2026-10"
    label: str
    start: date
    end: date


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


def _months(locale: str, today: date) -> list[Month]:
    """Os 12 últimos meses, o atual primeiro."""
    months = []
    first = today.replace(day=1)
    for _ in range(12):
        last = (first + timedelta(days=31)).replace(day=1) - timedelta(days=1)
        months.append(Month(f"{first:%Y-%m}", format_month(locale, first), first, last))
        first = (first - timedelta(days=1)).replace(day=1)
    return months


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
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


# --- estado da tela --------------------------------------------------------------------------


@dataclass
class Choice:
    """O modelo aberto: um pronto (`model` None) ou um da pessoa."""

    slug: str  # a aba na URL
    name: str
    config: ReportConfig | None  # None: o modelo salvo não vale mais (error)
    model: ReportModel | None = None


@dataclass
class State:
    """O que a tela e o CSV de um bloco tiram da URL: o modelo, o período e os filtros."""

    choice: Choice
    models: list[ReportModel]
    options: ReportOptions
    period: str
    start_text: str
    end_text: str
    start: date | None
    end: date | None
    teams: list[uuid.UUID]
    people: list[uuid.UUID]
    clients: list[uuid.UUID]
    no_client: bool
    statuses: list[int]
    compare: bool = False
    filters: service.Filters | None = None
    error: str | None = None
    warning: str | None = None
    query: dict[str, str | list[str] | None] = field(default_factory=dict)

    def specs(self) -> tuple[PeriodSpec, FilterSpec]:
        """O período e os filtros como o modelo os guarda. Um mês da lista vira as datas dele."""
        if self.period in RELATIVE:
            period = PeriodSpec(kind=self.period, compare=self.compare)
        else:
            period = PeriodSpec(kind=CUSTOM, start=self.start, end=self.end, compare=self.compare)
        filters = FilterSpec(
            teams=self.teams,
            people=self.people,
            clients=self.clients,
            no_client=self.no_client,
            statuses=self.statuses,
        )
        return period, filters


def _choice(page: LoggedPage, aba: str | None, models: list[ReportModel]) -> Choice:
    def builtin(slug: str) -> Choice:
        return Choice(slug, page.t(f"relatorios.abas.{TABS[slug]}"), BUILTINS[slug])

    if aba in BUILTINS:
        return builtin(aba)
    model = next((m for m in models if str(m.public_id) == aba), None)
    if model is None and aba is None:
        model = next((m for m in models if m.is_default), None)
    if model is None:
        return builtin("produtividade")
    try:
        config: ReportConfig | None = saved.config_of(model)
    except HTTPException:
        config = None
    return Choice(str(model.public_id), model.name, config, model)


async def _state(page: LoggedPage, db: DB, params: Params) -> State:
    auth = page.auth
    today = datetime.now(TIMEZONE).date()
    months = _months(page.locale, today)
    models = await saved.list_mine(db, auth)
    choice = _choice(page, params.aba, models)
    periodo, de, ate = params.periodo, params.de, params.ate
    grupo, pessoa, cliente, status = params.grupo, params.pessoa, params.cliente, params.status
    comparar = params.comparar
    options = await reports_api.report_options(auth, db)

    # Sem filtro na URL, valem os do modelo. Os salvos que deixaram de valer para a pessoa
    # (ex.: deixou de supervisionar o grupo) ficam de fora, com um aviso.
    warning = None
    url = (periodo, de, ate, grupo, pessoa, cliente, status, comparar)
    compare = comparar == "1"
    if all(v is None for v in url) and choice.config is not None:
        spec, saved_filters = choice.config.period, choice.config.filters
        periodo = spec.kind
        compare = spec.compare
        de = spec.start.isoformat() if spec.start else None
        ate = spec.end.isoformat() if spec.end else None
        lost = []
        teams = [t for t in saved_filters.teams if t in {o.id for o in options.teams}]
        if len(teams) < len(saved_filters.teams):
            lost.append(page.t("relatorios.grupo"))
        people = [p for p in saved_filters.people if p in {o.id for o in options.people}]
        if len(people) < len(saved_filters.people):
            lost.append(page.t("relatorios.pessoa"))
        clients = [c for c in saved_filters.clients if c in {o.id for o in options.clients}]
        if len(clients) < len(saved_filters.clients):
            lost.append(page.t("relatorios.cliente"))
        statuses = [s for s in saved_filters.statuses if s in {o.id for o in options.statuses}]
        if len(statuses) < len(saved_filters.statuses):
            lost.append(page.t("relatorios.status"))
        no_client = saved_filters.no_client
        if lost:
            warning = page.t("relatorios.filtrosSalvosInvalidos", filtros=", ".join(lost))
    else:
        teams, people, clients = _uuids(grupo), _uuids(pessoa), _uuids(cliente)
        no_client = NO_CLIENT in (cliente or [])
        statuses = [int(v) for v in status or [] if v.isdigit()]

    # Um período relativo, um mês da lista ou o personalizado; sem período (ou um desconhecido),
    # o mês atual. Ao escolher "Personalizado", as datas começam no primeiro dia do mês e em
    # hoje; uma data apagada é um período inválido.
    month = next((m for m in months if m.value == periodo), None)
    period = (
        periodo if periodo and (periodo in RELATIVE or periodo == CUSTOM or month) else "mes-atual"
    )
    if period in RELATIVE:
        first, last = builder.relative_period(period, today)
        start_text, end_text = first.isoformat(), last.isoformat()
    elif month:
        start_text, end_text = month.start.isoformat(), month.end.isoformat()
    else:
        start_text = months[0].start.isoformat() if de is None else de
        end_text = today.isoformat() if ate is None else ate
    start, end = _date(start_text), _date(end_text)

    state = State(
        choice=choice,
        models=models,
        options=options,
        period=period,
        start_text=start_text,
        end_text=end_text,
        start=start,
        end=end,
        teams=teams,
        people=people,
        clients=clients,
        no_client=no_client,
        statuses=statuses,
        compare=compare,
        warning=warning,
    )
    if choice.config is None:
        state.error = page.t("relatorios.modeloInvalido")
    elif start and end and start <= end:
        try:
            state.filters = await service.resolve(
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
        except HTTPException as exc:
            state.error = page.api_message(exc)
    state.query = {
        "periodo": period,
        "de": start_text if period == CUSTOM else None,
        "ate": end_text if period == CUSTOM else None,
        "grupo": [str(t) for t in teams],
        "pessoa": [str(p) for p in people],
        "cliente": ([NO_CLIENT] if no_client else []) + [str(c) for c in clients],
        "status": [str(s) for s in statuses],
        "comparar": "1" if compare else None,
    }
    return state


def _url(path: str, query: dict[str, Any]) -> str:
    params = {k: v for k, v in query.items() if v}
    return f"{path}?{urlencode(params, doseq=True)}" if params else path


# --- blocos ----------------------------------------------------------------------------------


Format = Callable[[builder.Value], str]


def _formatter(page: LoggedPage, config: ReportConfig, measure: str) -> Format:
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


def _title(page: LoggedPage, block: Block, dimension: str | None) -> str:
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


def _view(
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
        return _url("/relatorios/chamados", {**base, **(drill or {}), "medida": measure})

    # O em aberto agrupa pelo status do fim do período; o filtro de status é o atual.
    can_drill = not (dimension == "status" and "backlog" in block.measures)

    def drill_of(row: builder.Row) -> dict[str, Any] | None:
        return _drill(state, data, dimension, row.key) if can_drill else None

    def apply(row: builder.Row) -> str | None:
        drill = drill_of(row)
        return _url("/relatorios", {**base, **drill}) if drill else None

    view: dict[str, Any] = {
        "visual": block.visual,
        "title": _title(page, block, dimension),
        "csv": _url("/relatorios/csv", {**base, "bloco": str(index)}),
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
            fmt = _formatter(page, config, m)
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
            fmt=_formatter(page, config, "hours"),
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
            fmt=_formatter(page, config, m),
            step=_step(m, max((p.value for p in points), default=0)),
            empty=page.t(empty),
        )
    elif block.visual == "table":
        formats = [_formatter(page, config, m) for m in block.measures]
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
        fmt = _formatter(page, config, "hours")
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


def _interval(page: LoggedPage, state: State) -> str | None:
    start, end = state.start, state.end
    if not (start and end and start <= end):
        return None
    parts = []
    if state.period != CUSTOM:
        parts.append(
            page.t(
                "relatorios.intervalo",
                de=format_day(page.locale, start),
                ate=format_day(page.locale, end),
            )
        )
    if state.compare:
        first, last = builder.previous_period(
            start, end, year_to_date=state.period == "ano-ate-hoje"
        )
        parts.append(
            page.t(
                "relatorios.comparacao.com",
                de=format_day(page.locale, first),
                ate=format_day(page.locale, last),
            )
        )
    return " · ".join(parts) or None


def _uses_overtime(config: ReportConfig) -> bool:
    return any("overtime" in b.measures or b.only_overtime for b in config.blocks)


# --- tela ------------------------------------------------------------------------------------


@router.get("/relatorios")
async def reports_page(
    page: LoggedPageDep,
    db: DB,
    params: ParamsDep,
) -> HTMLResponse:
    state = await _state(page, db, params)
    choice, query, options = state.choice, state.query, state.options
    slug = choice.slug

    # Os modelos prontos levam os filtros da tela; o da pessoa abre com os que ele guarda.
    tabs = [
        (s, page.t(f"relatorios.abas.{key}"), _url("/relatorios", {**query, "aba": s}))
        for s, key in TABS.items()
    ] + [
        (str(m.public_id), m.name, _url("/relatorios", {"aba": str(m.public_id)}))
        for m in state.models
    ]

    blocks: list[dict[str, Any]] = []
    downloads = None
    work_hours = None
    f, config = state.filters, choice.config
    if f is not None and config is not None:
        data = await service.facts(db, page.auth, f)
        before = None
        if state.compare and any(b.visual == "cards" for b in config.blocks):
            first, last = builder.previous_period(
                f.start, f.end, year_to_date=state.period == "ano-ate-hoje"
            )
            before = await service.facts(db, page.auth, replace(f, start=first, end=last))
        blocks = [
            _view(page, state, f, config, data, block, i, before)
            for i, block in enumerate(config.blocks)
        ]
        if _uses_overtime(config):
            wh = data.work_hours
            work_hours = page.t(
                "relatorios.expedienteUsado",
                dias=", ".join(page.t(f"expediente.diasCurtos.{WEEKDAYS[d]}") for d in wh.weekdays),
                inicio=f"{wh.start:%H:%M}",
                fim=f"{wh.end:%H:%M}",
            )
        # Os downloads da API levam os mesmos filtros, com o idioma da pessoa (um link não
        # escolhe o Accept-Language). O PDF e a tabela da aba, só nos modelos prontos.
        api = {
            "start": f.start.isoformat(),
            "end": f.end.isoformat(),
            "team": query["grupo"],
            "person": query["pessoa"],
            "client": [str(c) for c in state.clients],
            "no_client": "true" if state.no_client else None,
            "status": query["status"],
            "locale": page.locale,
        }
        downloads = {"tarefas": _url("/api/v1/reports/csv", {**api, "table": "tasks"})}
        if slug in CSV_TABLES and choice.model is None:
            downloads["pdf"] = _url("/api/v1/reports/pdf", api)
            downloads["csv"] = _url("/api/v1/reports/csv", {**api, "table": CSV_TABLES[slug]})

    # "Salvar filtros": num modelo da pessoa, quando os da tela não são os guardados.
    filters_changed = False
    if choice.model is not None and config is not None and state.start and state.end:
        filters_changed = state.specs() != (config.period, config.filters)

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

    today = datetime.now(TIMEZONE).date()
    start, end = state.start, state.end
    return page.render(
        "reports/index.html",
        tabs=tabs,
        tab=slug,
        model=choice.model,
        period=state.period,
        period_groups=[
            (
                page.t("relatorios.periodosRelativos"),
                [(s, page.t(f"relatorios.periodos.{key}")) for s, key in RELATIVE_KEYS.items()],
            ),
            (
                page.t("relatorios.meses"),
                [(m.value, m.label) for m in _months(page.locale, today)],
            ),
        ],
        start=state.start_text,
        end=state.end_text,
        period_ok=bool(start and end and start <= end),
        # O intervalo de um período relativo ou de um mês (que não aparece nos campos de data)
        # e o de comparação.
        interval=_interval(page, state),
        compare=state.compare,
        filters=filters,
        query_fields=[
            (name, value)
            for name, values in query.items()
            if values
            for value in ([values] if isinstance(values, str) else values)
        ],
        filters_changed=filters_changed,
        new_model_url=_url("/relatorios/modelos/novo", {**query, "base": slug}),
        blocks=blocks,
        work_hours=work_hours,
        error=state.error,
        warning=state.warning,
        downloads=downloads,
    )


@router.get("/relatorios/csv")
async def block_csv(
    page: LoggedPageDep,
    db: DB,
    bloco: int,
    params: ParamsDep,
) -> Response:
    """O CSV de um bloco (docs/14 §14.8.4), com os filtros da tela; vai para a auditoria."""
    state = await _state(page, db, params)
    f, config = state.filters, state.choice.config
    if state.error or f is None or config is None:
        raise HTTPException(422, "Não foi possível gerar o CSV com estes filtros.")
    if not 0 <= bloco < len(config.blocks):
        raise HTTPException(404)
    block = config.blocks[bloco]
    data = await service.facts(db, page.auth, f)
    result = builder.run(data, block, f.start, f.end)
    content = csv_export.render_block(data, result, cast(Locale, page.locale))
    reports_api.record_export(
        db, page.request, page.auth, f, format="csv", table="block", model=state.choice.name
    )
    await db.commit()
    name = f"relatorio-bloco-{bloco + 1}-{f.start:%Y-%m-%d}-a-{f.end:%Y-%m-%d}.csv"
    return Response(
        content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/relatorios/chamados")
async def ticket_list(
    page: LoggedPageDep,
    db: DB,
    params: ParamsDep,
    medida: str,
    formato: str | None = None,
) -> Response:
    """Os chamados por trás de um número (detalhar, docs/14 §14.8.3), com os filtros da tela, e
    o CSV deles (`formato=csv`, que vai para a auditoria)."""
    if medida not in TICKET_SETS:
        raise HTTPException(404)
    measure = medida
    kind = TICKET_SETS[measure]
    state = await _state(page, db, params)
    f = state.filters
    base = {**state.query, "aba": state.choice.slug}
    context: dict[str, Any] = {
        "title": page.t(f"relatorios.medidas.{measure}"),
        "kind": kind,
        "back": _url("/relatorios", base),
        "interval": _interval(page, state),
        "error": state.error,
        "rows": [],
        "count": 0,
        "csv": _url("/relatorios/chamados", {**base, "medida": measure, "formato": "csv"}),
    }
    if f is None:
        if formato == "csv":
            raise HTTPException(422, "Não foi possível gerar o CSV com estes filtros.")
        context["error"] = state.error or page.t("relatorios.periodoInvalido")
        return page.render("reports/tickets.html", status_code=422, **context)

    data = await service.facts(db, page.auth, f)
    tickets = builder.tickets_of(data, measure)
    # Os mais recentes primeiro; no em aberto, os mais antigos (os que esperam há mais tempo).
    if kind == "backlog":
        tickets.sort(key=lambda t: t.created_at)
    else:
        tickets.sort(key=lambda t: t.finished_at or t.created_at, reverse=True)
    if formato == "csv":
        content = csv_export.render_tickets(data, tickets, kind, cast(Locale, page.locale))
        reports_api.record_export(
            db, page.request, page.auth, f, format="csv", table="tickets", measure=measure
        )
        await db.commit()
        name = f"relatorio-chamados-{f.start:%Y-%m-%d}-a-{f.end:%Y-%m-%d}.csv"
        return Response(
            content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    def client(ticket: service.TicketFact) -> str:
        found = data.clients.get(ticket.client_id) if ticket.client_id else None
        return found.label if found else page.t("relatorios.semCliente")

    context["rows"] = [
        {
            "number": t.number,
            "title": t.title,
            "client": client(t),
            "team": data.teams[t.team_id].name,
            "status": data.statuses[t.status_id].name,
            "people": ", ".join(sorted(data.users[u].display_name for u in t.people)),
            "created_at": t.created_at,
            "finished_at": t.finished_at,
            "lead": format_elapsed(t.lead) if t.lead is not None else "—",
            "net_lead": format_elapsed(t.net_lead) if t.net_lead is not None else "—",
            "reopened": t.reopened,
            "age": format_elapsed(t.age) if t.age is not None else "—",
        }
        for t in tickets[:LISTED]
    ]
    context["count"] = len(tickets)
    return page.render("reports/tickets.html", **context)


@router.post("/relatorios/modelos/{model_id}/filtros")
async def save_filters(
    page: LoggedPageDep,
    db: DB,
    model_id: uuid.UUID,
) -> Response:
    """Guarda no modelo o período e os filtros da tela."""
    form = await page.request.form()
    check_csrf(page, str(form.get("csrf_token", "")))
    model = await saved.get(db, page.auth, model_id)
    state = await _state(page, db, replace(_filter_params(form), aba=str(model_id)))
    response = RedirectResponse(_url("/relatorios", {"aba": str(model_id)}), status_code=303)
    if state.error or state.choice.config is None:
        page.flash(response, ("error", state.error or page.t("comum.erroInesperado")))
        return response
    period, filters = state.specs()
    await saved.save_filters(
        db, model, state.choice.config.model_copy(update={"period": period, "filters": filters})
    )
    await db.commit()
    page.flash(response, ("success", page.t("relatorios.filtrosSalvos")))
    return response


def _filter_params(form: FormData) -> Params:
    """Os filtros vindos num formulário (os mesmos nomes da URL); um ausente fica None."""

    def one(name: str) -> str | None:
        value = form.get(name)
        return value if isinstance(value, str) else None

    def many(name: str) -> list[str] | None:
        values = [v for v in form.getlist(name) if isinstance(v, str)]
        return values or None

    return Params(
        periodo=one("periodo"),
        de=one("de"),
        ate=one("ate"),
        grupo=many("grupo"),
        pessoa=many("pessoa"),
        cliente=many("cliente"),
        status=many("status"),
        comparar=one("comparar"),
    )


# --- editor ----------------------------------------------------------------------------------

NEW_BLOCK = Block(visual="table", dimension="person", measures=["hours"])


@dataclass
class EditorForm:
    name: str = ""
    hours: str = "hm"
    is_default: bool = False
    blocks: list[Block] = field(default_factory=list)
    errors: dict[int, str] = field(default_factory=dict)  # bloco → erro
    error: str | None = None


def _read_block(form: FormData, i: int) -> Block:
    """Um bloco do formulário. As escolhas que não cabem no visual (ex.: depois de trocá-lo) se
    ajustam: o agrupamento vai para um que ele aceita e a medida passa de uma para várias."""

    def one(name: str) -> str:
        value = form.get(f"b{i}-{name}")
        return value.strip() if isinstance(value, str) else ""

    visual = one("visual") if one("visual") in builder.VISUALS else "table"
    dimension = one("agrupar") if one("agrupar") in builder.DIMENSIONS else None
    if visual in ("cards", "tasks"):
        dimension = None
    elif visual == "bars" and dimension not in (*CATEGORIES, "age"):
        dimension = "person"
    elif (visual == "line" and dimension not in TIMES) or (
        visual == "stacked" and dimension in (None, "age")
    ):
        dimension = "day"
    elif dimension is None:
        dimension = "day" if visual == "columns" else "person"
    single = one("medida")
    checked = [v for v in form.getlist(f"b{i}-medidas") if isinstance(v, str)]
    measures = [m for m in builder.MEASURES if m in checked]
    if visual == "stacked":
        measures = list(STACKED)
    elif visual in CHARTS:
        chosen = single if single in builder.MEASURES else (measures or ["hours"])[0]
        measures = [chosen]
    elif not measures and single in builder.MEASURES:
        measures = [single]
    top = one("maiores")
    order = one("ordem")
    return Block(
        visual=visual,
        title=one("titulo")[:120],
        dimension=dimension,
        measures=measures,
        top=min(int(top), 100) if top.isdigit() and int(top) > 0 else None,
        order=order if order in ("desc", "asc", "name") else "desc",
        only_overtime=one("extras") == "1",
    )


def _read_editor(form: FormData) -> tuple[EditorForm, str]:
    count = form.get("blocos")
    total = min(int(count), 12) if isinstance(count, str) and count.isdigit() else 0
    hours = form.get("horas")
    editor = EditorForm(
        name=str(form.get("nome", "")),
        hours=hours if hours in ("hm", "decimal") else "hm",
        is_default=form.get("inicial") == "1",
        blocks=[_read_block(form, i) for i in range(total)],
    )
    return editor, str(form.get("acao", "salvar"))


def _apply(editor: EditorForm, action: str) -> None:
    """Adicionar, remover e mover blocos (o formulário volta sem salvar)."""
    blocks = editor.blocks
    if action == "adicionar" and len(blocks) < 12:
        blocks.append(NEW_BLOCK.model_copy())
        return
    verb, _, number = action.partition("-")
    if not number.isdigit() or int(number) >= len(blocks):
        return
    i = int(number)
    if verb == "remover":
        del blocks[i]
    elif verb == "subir" and i > 0:
        blocks[i - 1], blocks[i] = blocks[i], blocks[i - 1]
    elif verb == "descer" and i < len(blocks) - 1:
        blocks[i + 1], blocks[i] = blocks[i], blocks[i + 1]


def _editor_page(
    page: LoggedPage,
    editor: EditorForm,
    *,
    model: ReportModel | None,
    hidden: list[tuple[str, str]],
    back: str,
    status_code: int = 200,
) -> HTMLResponse:
    action = f"/relatorios/modelos/{model.public_id}" if model else "/relatorios/modelos"
    # O que cada visual agrupa: as barras, cadastros e idade; a linha, só períodos; a idade é
    # do em aberto, que não tem horas para empilhar.
    dimensions = {
        "bars": (*CATEGORIES, "age"),
        "columns": builder.DIMENSIONS,
        "stacked": tuple(d for d in builder.DIMENSIONS if d != "age"),
        "line": TIMES,
        "table": builder.DIMENSIONS,
    }
    return page.render(
        "reports/editor.html",
        status_code=status_code,
        form=editor,
        model=model,
        action=action,
        hidden=hidden,
        back=back,
        dimensions=dimensions,
        categories=CATEGORIES,
        charts=CHARTS,
        visual_options=[(v, page.t(f"relatorios.visuais.{v}")) for v in builder.VISUALS],
        dimension_options={
            visual: [(d, page.t(f"relatorios.dimensoes.{d}").capitalize()) for d in options]
            for visual, options in dimensions.items()
        },
        measure_options=[(m, page.t(f"relatorios.medidas.{m}")) for m in builder.MEASURES],
        order_options=[(o, page.t(f"relatorios.ordens.{o}")) for o in ("desc", "asc", "name")],
        placeholders=[
            _title(page, b, b.dimension) or page.t("relatorios.editor.semTitulo")
            for b in editor.blocks
        ],
    )


def _base(page: LoggedPage, base: str | None, models: list[ReportModel]) -> EditorForm:
    """O formulário de um modelo novo: os blocos do modelo de onde ele saiu."""
    source = next((m for m in models if str(m.public_id) == base), None)
    if source is not None:
        config = saved.config_of(source)
        name = page.t("relatorios.editor.copiaDe", nome=source.name)[: saved.MAX_NAME]
    else:
        config = BUILTINS.get(base or "", BUILTINS["produtividade"])
        name = ""
    return EditorForm(name=name, hours=config.hours, blocks=list(config.blocks))


@router.get("/relatorios/modelos/novo")
async def new_model(
    page: LoggedPageDep,
    db: DB,
    params: ParamsDep,
    base: str | None = None,
) -> HTMLResponse:
    """Salvar como modelo: os blocos do modelo aberto e os filtros da tela."""
    models = await saved.list_mine(db, page.auth)
    try:
        editor = _base(page, base, models)
    except HTTPException as exc:
        editor = EditorForm(blocks=[NEW_BLOCK], error=page.api_message(exc))
    return _editor_page(
        page, editor, model=None, hidden=params.hidden(), back=_url("/relatorios", {"aba": base})
    )


@router.get("/relatorios/modelos/{model_id}/editar")
async def edit_model(page: LoggedPageDep, db: DB, model_id: uuid.UUID) -> HTMLResponse:
    model = await saved.get(db, page.auth, model_id)
    back = _url("/relatorios", {"aba": str(model_id)})
    try:
        config = saved.config_of(model)
    except HTTPException as exc:
        editor = EditorForm(name=model.name, blocks=[NEW_BLOCK], error=page.api_message(exc))
    else:
        editor = EditorForm(
            name=model.name,
            hours=config.hours,
            is_default=model.is_default,
            blocks=list(config.blocks),
        )
    return _editor_page(page, editor, model=model, hidden=[], back=back)


@router.post("/relatorios/modelos")
async def create_model(page: LoggedPageDep, db: DB) -> Response:
    return await _submit(page, db, None)


@router.post("/relatorios/modelos/{model_id}")
async def update_model(page: LoggedPageDep, db: DB, model_id: uuid.UUID) -> Response:
    return await _submit(page, db, await saved.get(db, page.auth, model_id))


async def _submit(page: LoggedPage, db: DB, model: ReportModel | None) -> Response:
    """Salvar, ou só refazer o formulário (adicionar, remover, mover, trocar o visual)."""
    form = await page.request.form()
    check_csrf(page, str(form.get("csrf_token", "")))
    editor, action = _read_editor(form)
    hidden = _filter_params(form).hidden()
    back = _url("/relatorios", {"aba": str(model.public_id) if model else None})
    if action != "salvar":
        _apply(editor, action)
        return _editor_page(page, editor, model=model, hidden=hidden, back=back)

    for i, block in enumerate(editor.blocks):
        try:
            builder.check_block(block)
        except HTTPException as exc:
            editor.errors[i] = page.api_message(exc)
    if not editor.blocks:
        editor.error = page.t("relatorios.editor.semBlocos")
    if editor.errors or editor.error:
        return _editor_page(page, editor, model=model, hidden=hidden, back=back, status_code=422)

    try:
        if model is None:
            # O período e os filtros vêm da tela de onde o modelo saiu.
            state = await _state(page, db, _filter_params(form))
            period, filters = state.specs() if state.start and state.end else (None, None)
            config = ReportConfig(
                period=period or PeriodSpec(),
                filters=filters or FilterSpec(),
                hours=editor.hours,
                blocks=editor.blocks,
            )
        else:
            config = saved.config_of(model).model_copy(
                update={"hours": editor.hours, "blocks": editor.blocks}
            )
        model = await saved.save(
            db, page.auth, model, name=editor.name, config=config, is_default=editor.is_default
        )
    except HTTPException as exc:
        editor.error = page.api_message(exc)
        return _editor_page(page, editor, model=model, hidden=hidden, back=back, status_code=422)
    await db.commit()
    response = RedirectResponse(_url("/relatorios", {"aba": str(model.public_id)}), 303)
    page.flash(response, ("success", page.t("relatorios.editor.salvo")))
    return response


@router.post("/relatorios/modelos/{model_id}/excluir")
async def delete_model(page: LoggedPageDep, db: DB, model_id: uuid.UUID) -> Response:
    form = await page.request.form()
    check_csrf(page, str(form.get("csrf_token", "")))
    model = await saved.get(db, page.auth, model_id)
    await saved.delete(db, model)
    await db.commit()
    response = RedirectResponse("/relatorios", status_code=303)
    page.flash(response, ("success", page.t("relatorios.editor.excluido")))
    return response
