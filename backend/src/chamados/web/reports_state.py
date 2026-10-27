"""Relatórios: o que a tela tira da URL (docs/14 §14.8). O modelo (`aba`), o período e os
filtros ficam na URL, como na lista de chamados. Grupo, pessoa, cliente e status aceitam vários
valores (o parâmetro repetido). Sem nenhum filtro na URL, valem os salvos no modelo; o formulário
sempre manda o período, então mexer num filtro passa a valer o da URL, e "Salvar filtros" o
guarda no modelo.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import Depends, HTTPException, Query
from starlette.datastructures import FormData

from chamados.db.session import DB
from chamados.modules.reports import builder, saved, service
from chamados.modules.reports.builder import (
    BUILTINS,
    CUSTOM,
    LAST_DAYS,
    RELATIVE,
    Compare,
    FilterSpec,
    PeriodSpec,
    ReportConfig,
)
from chamados.modules.reports.models import ReportModel
from chamados.modules.reports.service import MAX_DAYS
from chamados.web.formatting import TIMEZONE, format_day, format_month
from chamados.web.page import LoggedPage

# Modelo pronto (slug da aba na URL) → chave do catálogo (relatorios.abas.*).
TABS = {
    "produtividade": "produtividade",
    "clientes": "clientes",
    "horas-extras": "horasExtras",
    "chamados": "chamados",
}


NO_CLIENT = "sem-cliente"

# A comparação na URL (`comparar`) → `PeriodSpec.compare`. O "1" é o dos links de quando só se
# comparava com o período anterior.
COMPARE: dict[str, Compare] = {"anterior": "previous", "ano": "year", "1": "previous"}
COMPARE_SLUGS: dict[Compare, str] = {"previous": "anterior", "year": "ano"}


# Período relativo (slug) → chave do catálogo (relatorios.periodos.*).
RELATIVE_KEYS = dict(
    zip(
        RELATIVE,
        (
            "semanaAtual",
            "semanaAnterior",
            "mesAtual",
            "mesAnterior",
            "ultimos7",
            "ultimos30",
            "ultimos90",
            "ultimosN",
            "trimestreAtual",
            "trimestreAnterior",
            "anoAteHoje",
            "anoAnterior",
            "ultimos12Meses",
        ),
        strict=True,
    )
)


Values = Annotated[list[str] | None, Query()]


@dataclass
class Params:
    """O modelo e os filtros como vêm na URL (ou num formulário, com os mesmos nomes); um ausente
    é None. Sem nenhum filtro, valem os salvos no modelo."""

    aba: str | None = None
    periodo: str | None = None
    de: str | None = None
    ate: str | None = None
    dias: str | None = None  # os N do "ultimos-n-dias"
    grupo: Values = None
    pessoa: Values = None
    cliente: Values = None
    status: Values = None
    comparar: str | None = None
    # O período de onde o detalhar saiu (a trilha da tela): um relativo, um mês da lista ou
    # "de_ate". Não é filtro: não conta para "sem nenhum filtro na URL".
    origem: str | None = None

    def hidden(self) -> list[tuple[str, str]]:
        """Os filtros em campos escondidos de um formulário."""
        fields = []
        for name in FILTER_FIELDS:
            value = getattr(self, name)
            fields += [(name, v) for v in ([value] if isinstance(value, str) else value or [])]
        return fields


ParamsDep = Annotated[Params, Depends()]


FILTER_FIELDS = ("periodo", "de", "ate", "dias", "grupo", "pessoa", "cliente", "status", "comparar")


@dataclass
class Month:
    value: str  # "2026-10"
    label: str
    start: date
    end: date


def last_months(locale: str, today: date) -> list[Month]:
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


def parse_days(value: str | None) -> int | None:
    """Os N dias do "ultimos-n-dias", de 1 a MAX_DAYS; fora disso (ou sem número), None."""
    if not (value and value.isascii() and value.isdigit() and len(value) <= 3):
        return None  # "²" é dígito para o isdigit, mas não para o int
    return int(value) if 1 <= int(value) <= MAX_DAYS else None


def parse_uuids(values: list[str] | None) -> list[uuid.UUID]:
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
    options: service.Choices
    lookups: service.Lookups  # o expediente e os status, lidos uma vez (`service.facts`)
    period: str
    start_text: str
    end_text: str
    start: date | None
    end: date | None
    days: int | None  # os N do "ultimos-n-dias"; None nos outros períodos
    teams: list[uuid.UUID]
    people: list[uuid.UUID]
    clients: list[uuid.UUID]
    no_client: bool
    statuses: list[int]
    client_names: dict[uuid.UUID, str] = field(default_factory=dict)  # os escolhidos
    compare: Compare = "none"
    origin: str | None = None  # Params.origem, só no personalizado
    filters: service.Filters | None = None
    error: str | None = None
    warning: str | None = None
    query: dict[str, str | list[str] | None] = field(default_factory=dict)

    def comparison(self) -> tuple[date, date] | None:
        """O período com que se compara; sem comparar (ou sem um período válido), None."""
        if not (self.start and self.end and self.start <= self.end):
            return None
        try:
            return builder.comparison_period(
                self.start, self.end, self.compare, year_to_date=self.period == "ano-ate-hoje"
            )
        except ValueError:  # antes do ano 1: não há com que comparar
            return None

    def specs(self) -> tuple[PeriodSpec, FilterSpec]:
        """O período e os filtros como o modelo os guarda. Um mês da lista vira as datas dele."""
        if self.period in RELATIVE:
            period = PeriodSpec(kind=self.period, days=self.days, compare=self.compare)
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


async def load_state(page: LoggedPage, db: DB, params: Params) -> State:
    auth = page.auth
    today = datetime.now(TIMEZONE).date()
    months = last_months(page.locale, today)
    models = await saved.list_mine(db, auth)
    choice = _choice(page, params.aba, models)
    periodo, de, ate, dias = params.periodo, params.de, params.ate, params.dias
    grupo, pessoa, cliente, status = params.grupo, params.pessoa, params.cliente, params.status
    comparar = params.comparar
    lookups = await service.lookups(db)
    options = await service.choices(db, auth, lookups.statuses)

    # Sem filtro na URL, valem os do modelo. Os salvos que deixaram de valer para a pessoa
    # (ex.: deixou de supervisionar o grupo) ficam de fora, com um aviso.
    warning = None
    url = (periodo, de, ate, dias, grupo, pessoa, cliente, status, comparar)
    compare: Compare = COMPARE.get(comparar or "", "none")
    if all(v is None for v in url) and choice.config is not None:
        spec, saved_filters = choice.config.period, choice.config.filters
        periodo = spec.kind
        compare = spec.compare
        de = spec.start.isoformat() if spec.start else None
        ate = spec.end.isoformat() if spec.end else None
        dias = str(spec.days) if spec.days else None
        lost = []
        teams = [t for t in saved_filters.teams if t in {o.id for o in options.teams}]
        if len(teams) < len(saved_filters.teams):
            lost.append(page.t("relatorios.grupo"))
        people = [p for p in saved_filters.people if p in {o.id for o in options.people}]
        if len(people) < len(saved_filters.people):
            lost.append(page.t("relatorios.pessoa"))
        client_names = await service.client_labels(db, saved_filters.clients)
        clients = [c for c in saved_filters.clients if c in client_names]
        if len(clients) < len(saved_filters.clients):
            lost.append(page.t("relatorios.cliente"))
        statuses = [s for s in saved_filters.statuses if s in {o.id for o in options.statuses}]
        if len(statuses) < len(saved_filters.statuses):
            lost.append(page.t("relatorios.status"))
        no_client = saved_filters.no_client
        if lost:
            warning = page.t("relatorios.filtrosSalvosInvalidos", filtros=", ".join(lost))
    else:
        teams, people, clients = parse_uuids(grupo), parse_uuids(pessoa), parse_uuids(cliente)
        client_names = await service.client_labels(db, clients)
        no_client = NO_CLIENT in (cliente or [])
        statuses = [int(v) for v in status or [] if v.isascii() and v.isdigit() and len(v) <= 5]

    # Um período relativo, um mês da lista ou o personalizado; sem período (ou um desconhecido),
    # o mês atual. Ao escolher "Personalizado", as datas começam no primeiro dia do mês e em
    # hoje; uma data apagada é um período inválido.
    month = next((m for m in months if m.value == periodo), None)
    period = (
        periodo if periodo and (periodo in RELATIVE or periodo == CUSTOM or month) else "mes-atual"
    )
    # Os N dias: um número fora de 1 a MAX_DAYS (ou apagado) volta ao padrão.
    days = (parse_days(dias) or builder.DEFAULT_DAYS) if period == LAST_DAYS else None
    if period in RELATIVE:
        first, last = builder.relative_period(period, today, days)
        start_text, end_text = first.isoformat(), last.isoformat()
    elif month:
        start_text, end_text = month.start.isoformat(), month.end.isoformat()
    else:
        start_text = months[0].start.isoformat() if de is None else de
        end_text = today.isoformat() if ate is None else ate
    start, end = _date(start_text), _date(end_text)

    origin = params.origem if period == CUSTOM else None
    if origin is not None and not (
        (origin in RELATIVE and origin != LAST_DAYS)
        or _last_days(origin)
        or any(m.value == origin for m in months)
        or _span(origin)
    ):
        origin = None

    state = State(
        choice=choice,
        models=models,
        options=options,
        lookups=lookups,
        period=period,
        start_text=start_text,
        end_text=end_text,
        start=start,
        end=end,
        days=days,
        teams=teams,
        people=people,
        clients=clients,
        no_client=no_client,
        statuses=statuses,
        client_names=client_names,
        compare=compare,
        origin=origin,
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
        "dias": str(days) if days else None,
        "grupo": [str(t) for t in teams],
        "pessoa": [str(p) for p in people],
        "cliente": ([NO_CLIENT] if no_client else []) + [str(c) for c in clients],
        "status": [str(s) for s in statuses],
        "comparar": COMPARE_SLUGS.get(compare),
        "origem": origin,
    }
    return state


def _span(value: str) -> tuple[date, date] | None:
    """As duas datas de um "de_ate" (a origem personalizada)."""
    first, _, last = value.partition("_")
    start, end = _date(first), _date(last)
    return (start, end) if start and end and start <= end else None


def _last_days(value: str) -> int | None:
    """Os N de uma origem "ultimos-n-dias:N"."""
    slug, _, days = value.partition(":")
    return parse_days(days) if slug == LAST_DAYS else None


def origin_of(state: State) -> str:
    """O período aberto como origem do detalhar: o slug (relativo ou mês), "ultimos-n-dias:N"
    ou "de_ate"."""
    if state.period == CUSTOM:
        return f"{state.start_text}_{state.end_text}"
    if state.period == LAST_DAYS:
        return f"{LAST_DAYS}:{state.days}"
    return state.period


def origin_view(page: LoggedPage, state: State) -> tuple[str, dict[str, str]] | None:
    """O nome do período de onde o detalhar saiu e a query que volta a ele."""
    if state.origin is None:
        return None
    span = _span(state.origin)
    if span:
        label = page.t(
            "relatorios.detalhe.intervalo",
            de=format_day(page.locale, span[0]),
            ate=format_day(page.locale, span[1]),
        )
        return label, {"periodo": CUSTOM, "de": span[0].isoformat(), "ate": span[1].isoformat()}
    days = _last_days(state.origin)
    if days:
        key = "ultimoDia" if days == 1 else "ultimosNDias"
        label = page.t(f"relatorios.periodos.{key}", n=days)
        return label, {"periodo": LAST_DAYS, "dias": str(days)}
    if state.origin in RELATIVE_KEYS:
        label = page.t(f"relatorios.periodos.{RELATIVE_KEYS[state.origin]}")
        return label, {"periodo": state.origin}
    today = datetime.now(TIMEZONE).date()
    month = next((m for m in last_months(page.locale, today) if m.value == state.origin), None)
    return (month.label, {"periodo": state.origin}) if month else None


def with_query(path: str, query: dict[str, Any]) -> str:
    params = {k: v for k, v in query.items() if v}
    return f"{path}?{urlencode(params, doseq=True)}" if params else path


def interval_text(page: LoggedPage, state: State) -> str | None:
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
    if compared := state.comparison():
        first, last = compared
        parts.append(
            page.t(
                "relatorios.comparacao.com",
                de=format_day(page.locale, first),
                ate=format_day(page.locale, last),
            )
        )
    return " · ".join(parts) or None


def form_params(form: FormData) -> Params:
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
        dias=one("dias"),
        grupo=many("grupo"),
        pessoa=many("pessoa"),
        cliente=many("cliente"),
        status=many("status"),
        comparar=one("comparar"),
    )
