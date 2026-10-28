"""Relatórios: o que a tela tira da URL (docs/14 §14.8). A aba, o período e os filtros ficam
na URL, como na lista de chamados. Grupo, pessoa, cliente e status aceitam vários valores (o
parâmetro repetido). Sem nenhum filtro na URL, vale o mês atual (e, na aba Clientes, os
concluídos); o formulário sempre manda o período, então mexer num filtro passa a valer o da URL.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import Depends, HTTPException, Query

from chamados.db.session import DB
from chamados.modules.reports import builder, service
from chamados.modules.reports.builder import (
    BUILTINS,
    CUSTOM,
    LAST_DAYS,
    RELATIVE,
    Compare,
    ReportConfig,
)
from chamados.modules.reports.service import MAX_DAYS
from chamados.web.formatting import TIMEZONE, format_day, format_month
from chamados.web.page import LoggedPage

# Aba pronta (slug na URL) → chave do catálogo (relatorios.abas.*), na ordem das abas.
TABS = {
    "produtividade": "produtividade",
    "clientes": "clientes",
    "horas-extras": "horasExtras",
    "chamados": "chamados",
}


NO_CLIENT = "sem-cliente"

# A comparação na URL (`comparar`) → `Compare`. O "1" é o dos links de quando só se
# comparava com o período anterior.
COMPARE: dict[str, Compare] = {"anterior": "previous", "ano": "year", "1": "previous"}
COMPARE_SLUGS: dict[Compare, str] = {"previous": "anterior", "year": "ano"}
SEPARATE = "separada"  # Params.extras: a hora extra à parte, na aba Clientes


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
    """A aba e os filtros como vêm na URL; um ausente é None."""

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
    # Na aba Clientes, "separada": as horas no expediente e as extras à parte (sem, todo o tempo
    # é de trabalho normal).
    extras: str | None = None
    # Na aba Clientes, com um cliente só: as horas descontadas ("2:30", "2h30").
    desconto: str | None = None
    # Na aba Clientes, "1": a cascata (os clientes com relatório da pessoa hoje saem da lista de
    # clientes).
    cascata: str | None = None
    # O período de onde o detalhar saiu (a trilha da tela): um relativo, um mês da lista ou
    # "de_ate".
    origem: str | None = None


ParamsDep = Annotated[Params, Depends()]


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


def parse_int(value: object, digits: int) -> int | None:
    """Um número de até `digits` algarismos de 0 a 9; o resto, None ("²" é dígito para o
    isdigit, mas não para o int)."""
    if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= digits:
        return int(value)
    return None


def parse_days(value: str | None) -> int | None:
    """Os N dias do "ultimos-n-dias", de 1 a MAX_DAYS; fora disso (ou sem número), None."""
    days = parse_int(value, 3)
    return days if days is not None and 1 <= days <= MAX_DAYS else None


HOURS = re.compile(r"(\d{1,5})(?:[:h](\d{1,2})?(?:min)?)?")


def parse_minutes(value: str) -> int | None:
    """Horas e minutos ("2:30", "2h30", "2h", "2") ou só minutos ("45min"), em minutos; o que
    não se entende (ou minutos de 60 em diante), None."""
    value = value.strip().lower().replace(" ", "")
    if found := HOURS.fullmatch(value):
        minutes = int(found[2] or 0)
        return int(found[1]) * 60 + minutes if minutes < 60 else None
    if found := re.fullmatch(r"(\d{1,6})min", value):
        return int(found[1])
    return None


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
    """A aba aberta."""

    slug: str  # a aba na URL
    name: str
    config: ReportConfig


@dataclass
class State:
    """O que a tela e o CSV de um bloco tiram da URL: a aba, o período e os filtros."""

    choice: Choice
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
    separate: bool = False  # Params.extras, só na aba Clientes
    # Params.desconto: o campo aparece na aba Clientes com um cliente só; os minutos (0 sem
    # desconto) e se o texto não se entendeu.
    discount_field: bool = False
    discount: int = 0
    discount_invalid: bool = False
    cascade: bool = False  # Params.cascata, só na aba Clientes
    origin: str | None = None  # Params.origem, só no personalizado
    filters: service.Filters | None = None
    error: str | None = None
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


def closed_statuses(lookups: service.Lookups) -> list[int]:
    """Os status de situação concluída: o filtro de status com que a aba Clientes abre."""
    return [s.id for s in lookups.statuses if s.kind == "closed"]


def description_of(page: LoggedPage, choice: Choice) -> str:
    """O que a aba mostra, do catálogo."""
    return page.t(f"relatorios.descricoes.{TABS[choice.slug]}")


async def load_state(page: LoggedPage, db: DB, params: Params) -> State:
    auth = page.auth
    today = datetime.now(TIMEZONE).date()
    months = last_months(page.locale, today)
    slug = params.aba if params.aba in BUILTINS else "produtividade"
    choice = Choice(slug, page.t(f"relatorios.abas.{TABS[slug]}"), BUILTINS[slug])
    periodo, de, ate, dias = params.periodo, params.de, params.ate, params.dias
    grupo, pessoa, cliente, status = params.grupo, params.pessoa, params.cliente, params.status
    lookups = await service.lookups(db)
    options = await service.choices(db, auth, lookups.statuses)
    # Na aba Clientes, escolhida, a hora extra separada.
    separate = slug == "clientes" and params.extras == SEPARATE
    if separate:
        choice.config = builder.CLIENTS_OVERTIME

    compare: Compare = COMPARE.get(params.comparar or "", "none")
    teams, people, clients = parse_uuids(grupo), parse_uuids(pessoa), parse_uuids(cliente)
    client_names = await service.client_labels(db, clients)
    no_client = NO_CLIENT in (cliente or [])
    statuses = [n for v in status or [] if (n := parse_int(v, 5)) is not None]
    # A aba Clientes abre (sem nenhum filtro na URL) com os chamados concluídos.
    url = (periodo, de, ate, dias, grupo, pessoa, cliente, status, params.comparar)
    if slug == "clientes" and all(v is None for v in url):
        statuses = closed_statuses(lookups)

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

    # As horas descontadas: na aba Clientes, filtrada por um cliente só; com elas, o desconto e
    # as horas a cobrar entram nos blocos.
    discount_field = slug == "clientes" and len(clients) == 1 and not no_client
    discount_text = (params.desconto or "").strip() if discount_field else ""
    discount = parse_minutes(discount_text) if discount_text else 0
    if discount:
        choice.config = builder.with_discount(choice.config)
    cascade = slug == "clientes" and params.cascata == "1"

    state = State(
        choice=choice,
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
        separate=separate,
        discount_field=discount_field,
        discount=discount or 0,
        discount_invalid=discount is None,
        cascade=cascade,
        origin=origin,
    )
    if start and end and start <= end:
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
            state.filters.discount = state.discount
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
        "extras": SEPARATE if separate else None,
        "desconto": discount_text or None,
        "cascata": "1" if cascade else None,
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
