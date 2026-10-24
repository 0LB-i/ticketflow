"""Construtor guiado dos relatórios (docs/14 §14.8): a configuração de um modelo (período,
filtros e blocos), os modelos prontos e o cálculo de cada bloco a partir dos dados do período
(`service.facts`).

Cada bloco é "agrupar por × medida × visual", escolhidos em listas fechadas: nada do que a pessoa
escolhe vira SQL. As medidas vêm das tarefas (horas, horas extras, tarefas) ou dos chamados
(registrados, concluídos, cancelados, em aberto no fim, tempo até a conclusão, reabertura); com o
agrupamento por pessoa, um chamado conta para cada responsável. As contagens e as horas somam; os
tempos até a conclusão são a mediana (§14.1) e a reabertura, a porcentagem dos concluídos.
"""

import statistics
import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from chamados.modules.reports.service import Facts, TaskFact, TicketFact

Visual = Literal["cards", "bars", "columns", "stacked", "line", "table", "tasks"]
Dimension = Literal["person", "client", "team", "status", "age", "day", "week", "month"]
Measure = Literal[
    "hours",
    "overtime",
    "tasks",
    "opened",
    "closed",
    "canceled",
    "backlog",
    "lead_time",
    "net_lead_time",
    "reopen_rate",
]
Order = Literal["desc", "asc", "name"]

VISUALS: tuple[Visual, ...] = ("cards", "bars", "columns", "stacked", "line", "table", "tasks")
DIMENSIONS: tuple[Dimension, ...] = (
    "person",
    "client",
    "team",
    "status",
    "age",
    "day",
    "week",
    "month",
)
CATEGORIES: tuple[Dimension, ...] = ("person", "client", "team", "status")
TIMES: tuple[Dimension, ...] = ("day", "week", "month")
MEASURES: tuple[Measure, ...] = (
    "hours",
    "overtime",
    "tasks",
    "opened",
    "closed",
    "canceled",
    "backlog",
    "lead_time",
    "net_lead_time",
    "reopen_rate",
)
DURATIONS: tuple[Measure, ...] = ("hours", "overtime")  # minutos somados
ELAPSED: tuple[Measure, ...] = ("lead_time", "net_lead_time")  # minutos, pela mediana
PERCENT: tuple[Measure, ...] = ("reopen_rate",)  # em centésimos de ponto (1250 = 12,5%)
# Os chamados por trás de cada medida de chamado (a lista do "detalhar").
TICKET_SETS: dict[Measure, str] = {
    "opened": "opened",
    "closed": "closed",
    "canceled": "canceled",
    "backlog": "backlog",
    "lead_time": "closed",
    "net_lead_time": "closed",
    "reopen_rate": "closed",
}
CHARTS: tuple[Visual, ...] = ("bars", "columns", "stacked", "line")
# Idade do em aberto no fim do período (§14.3): até 1 dia, 1 a 3, 3 a 7, mais de 7 (em minutos).
AGE_LIMITS = (24 * 60, 3 * 24 * 60, 7 * 24 * 60)
STACKED: list[Measure] = ["hours", "overtime"]  # no expediente (horas − extras) e extras

# Períodos que andam com o calendário (os slugs também são os da URL da tela).
RELATIVE = (
    "mes-atual",
    "mes-anterior",
    "ultimos-7-dias",
    "ultimos-30-dias",
    "ultimos-90-dias",
    "trimestre-atual",
    "trimestre-anterior",
    "ano-ate-hoje",
)
CUSTOM = "personalizado"
OTHERS = "outros"  # a chave da linha que junta o que passou dos N maiores
MAX_MODELS = 50


class Block(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visual: Visual
    title: str = Field(default="", max_length=120)  # vazio: o título automático
    dimension: Dimension | None = None
    measures: list[Measure] = Field(default=[], max_length=len(MEASURES))
    top: int | None = Field(default=None, ge=1, le=100)  # só os N maiores; o resto em "Outros"
    order: Order = "desc"
    only_overtime: bool = False  # lista de tarefas: só as que têm tempo fora do expediente


class PeriodSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "mes-atual",
        "mes-anterior",
        "ultimos-7-dias",
        "ultimos-30-dias",
        "ultimos-90-dias",
        "trimestre-atual",
        "trimestre-anterior",
        "ano-ate-hoje",
        "personalizado",
    ] = "mes-atual"
    start: date | None = None  # só no personalizado
    end: date | None = None
    compare: bool = False  # os cartões mostram a variação sobre o período anterior


class FilterSpec(BaseModel):
    """Os filtros salvos: os mesmos de `service.resolve`, pelos ids públicos."""

    model_config = ConfigDict(extra="forbid")

    teams: list[uuid.UUID] = []
    people: list[uuid.UUID] = []
    clients: list[uuid.UUID] = []
    no_client: bool = False
    statuses: list[int] = []


class ReportConfig(BaseModel):
    """O que um modelo guarda (`report_models.config`). `version` muda quando o formato mudar
    de um jeito que os modelos salvos precisem ser convertidos."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    period: PeriodSpec = PeriodSpec()
    filters: FilterSpec = FilterSpec()
    hours: Literal["hm", "decimal"] = "hm"  # 7h30 ou 7,5 h
    # Para o cliente (§14.8.5): o PDF tem um formato fixo (totais e chamados) e os blocos não
    # aparecem; `show_people`, mostrar quem atendeu (os responsáveis).
    audience: Literal["internal", "client"] = "internal"
    show_people: bool = False
    blocks: list[Block] = Field(max_length=12)

    @model_validator(mode="after")
    def _has_blocks(self) -> "ReportConfig":
        if self.audience == "internal" and not self.blocks:
            raise ValueError("um modelo interno precisa de ao menos um bloco")
        return self


_CARDS = Block(visual="cards", measures=["hours", "overtime", "tasks", "opened", "closed"])

# Os modelos prontos (as telas da §14.7 e os indicadores de chamados da §14.3): não se apagam;
# duplicar leva os blocos.
BUILTINS: dict[str, ReportConfig] = {
    "produtividade": ReportConfig(
        blocks=[
            _CARDS,
            Block(visual="columns", dimension="day", measures=["hours"]),
            Block(visual="bars", dimension="person", measures=["hours"]),
            Block(
                visual="table",
                dimension="person",
                measures=["hours", "overtime", "tasks", "closed"],
            ),
        ]
    ),
    "clientes": ReportConfig(
        blocks=[
            _CARDS,
            Block(visual="bars", dimension="client", measures=["hours"], top=10),
            Block(visual="table", dimension="client", measures=["hours", "opened", "closed"]),
        ]
    ),
    "horas-extras": ReportConfig(
        blocks=[
            _CARDS,
            Block(visual="columns", dimension="day", measures=["overtime"]),
            Block(visual="bars", dimension="person", measures=["overtime"]),
            Block(visual="tasks", only_overtime=True),
        ]
    ),
    "chamados": ReportConfig(
        blocks=[
            Block(visual="cards", measures=["opened", "closed", "canceled", "backlog"]),
            Block(visual="cards", measures=["lead_time", "net_lead_time", "reopen_rate"]),
            Block(visual="line", dimension="week", measures=["opened"]),
            Block(visual="line", dimension="week", measures=["closed"]),
            Block(visual="columns", dimension="age", measures=["backlog"]),
            Block(visual="bars", dimension="status", measures=["backlog"]),
            Block(
                visual="table",
                dimension="team",
                measures=["opened", "closed", "canceled", "backlog", "lead_time", "reopen_rate"],
            ),
        ]
    ),
}


def check_block(block: Block) -> None:
    """As combinações que o formulário não deixa escolher, conferidas de novo ao salvar."""
    if block.visual == "tasks":
        return
    if block.visual != "cards" and block.dimension is None:
        raise HTTPException(422, "Escolha o que agrupar.")
    if not block.measures:
        raise HTTPException(422, "Escolha ao menos uma medida.")
    if block.visual in CHARTS and block.visual != "stacked" and len(block.measures) != 1:
        raise HTTPException(422, "Um gráfico mostra uma medida só.")
    if block.visual == "line" and block.dimension not in TIMES:
        raise HTTPException(422, "A linha agrupa por dia, semana ou mês.")
    if block.visual == "bars" and block.dimension not in (*CATEGORIES, "age"):
        raise HTTPException(422, "As barras agrupam por pessoa, cliente, grupo, status ou idade.")
    if block.visual == "stacked" and block.measures != STACKED:
        raise HTTPException(
            422, "As colunas empilhadas mostram as horas no expediente e as extras."
        )
    if block.dimension == "age" and set(block.measures) != {"backlog"}:
        raise HTTPException(422, "A idade só vale para a medida Em aberto.")
    if block.dimension in TIMES and "backlog" in block.measures:
        raise HTTPException(
            422, "Em aberto é o retrato do fim do período: não se agrupa por dia, semana ou mês."
        )


def _quarter(day: date) -> tuple[date, date]:
    first = date(day.year, (day.month - 1) // 3 * 3 + 1, 1)
    after = date(first.year + (first.month == 10), (first.month + 2) % 12 + 1, 1)
    return first, after - timedelta(days=1)


def _month(day: date) -> tuple[date, date]:
    first = day.replace(day=1)
    return first, (first + timedelta(days=31)).replace(day=1) - timedelta(days=1)


def previous_period(start: date, end: date, *, year_to_date: bool = False) -> tuple[date, date]:
    """O período de comparação: o ano até a data ("ano-ate-hoje"), com as mesmas datas do ano
    anterior; meses inteiros, com os meses de antes; os demais, com o mesmo número de dias logo
    antes."""
    if year_to_date:
        last = end - timedelta(days=1) if (end.month, end.day) == (2, 29) else end
        return start.replace(year=start.year - 1), last.replace(year=end.year - 1)
    after = end + timedelta(days=1)
    if start.day == 1 and after.day == 1:
        months = (after.year - start.year) * 12 + after.month - start.month
        index = start.year * 12 + start.month - 1 - months
        return date(index // 12, index % 12 + 1, 1), start - timedelta(days=1)
    length = (end - start).days + 1
    return start - timedelta(days=length), start - timedelta(days=1)


def relative_period(slug: str, today: date) -> tuple[date, date]:
    """O início e o fim (incluído) de um período de RELATIVE. O mês e o trimestre vão até o
    último dia, como os meses da lista da tela; os demais terminam hoje."""
    if slug == "mes-atual":
        return _month(today)
    if slug == "mes-anterior":
        return _month(today.replace(day=1) - timedelta(days=1))
    if slug == "trimestre-atual":
        return _quarter(today)
    if slug == "trimestre-anterior":
        return _quarter(_quarter(today)[0] - timedelta(days=1))
    if slug == "ano-ate-hoje":
        return today.replace(month=1, day=1), today
    days = {"ultimos-7-dias": 7, "ultimos-30-dias": 30, "ultimos-90-dias": 90}[slug]
    return today - timedelta(days=days - 1), today


# --- cálculo ---------------------------------------------------------------------------------

Key = int | date | str | None  # id do cadastro, dia, faixa de idade, OTHERS ou None (sem cliente)
Value = int | None  # None: medida sem base (mediana ou porcentagem de nada)


@dataclass
class Row:
    key: Key
    label: str | None  # nome do cadastro; None nos períodos, nas idades e no "sem cliente"
    values: dict[Measure, Value]


@dataclass
class Result:
    """Um bloco calculado. `rows` vem na ordem de exibição; `total` é o do período inteiro (um
    chamado com dois responsáveis conta uma vez, mesmo que apareça nas linhas dos dois)."""

    dimension: Dimension | None
    rows: list[Row] = field(default_factory=list)
    total: dict[Measure, Value] = field(default_factory=dict)
    is_list: bool = False  # a lista de tarefas (`tasks`), sem agrupar
    tasks: list[TaskFact] = field(default_factory=list)


def tickets_of(data: Facts, measure: Measure) -> list[TicketFact]:
    """Os chamados por trás de uma medida de chamado."""
    return list(getattr(data, TICKET_SETS[measure]))


def _contributions(data: Facts, measure: Measure) -> list[tuple[TaskFact | TicketFact, int]]:
    if measure == "hours":
        return [(t, t.minutes) for t in data.tasks]
    if measure == "overtime":
        return [(t, t.overtime) for t in data.tasks]
    if measure == "tasks":
        return [(t, 1) for t in data.tasks]
    if measure == "lead_time":
        return [(t, t.lead) for t in data.closed if t.lead is not None]
    if measure == "net_lead_time":
        return [(t, t.net_lead) for t in data.closed if t.net_lead is not None]
    if measure == "reopen_rate":
        return [(t, 10000 if t.reopened else 0) for t in data.closed]
    return [(t, 1) for t in tickets_of(data, measure)]


def _reduce(measure: Measure, amounts: list[int]) -> Value:
    if measure in ELAPSED:
        return round(statistics.median(amounts)) if amounts else None
    if measure in PERCENT:
        return round(statistics.fmean(amounts)) if amounts else None
    return sum(amounts)


def _keys(fact: TaskFact | TicketFact, dimension: Dimension) -> Iterable[Key]:
    if dimension == "person":
        return [fact.author_id] if isinstance(fact, TaskFact) else fact.people
    if dimension == "client":
        return [fact.client_id]
    if dimension == "team":
        return [fact.team_id]
    if dimension == "status":
        return [fact.status_id]
    if dimension == "age":
        age = fact.age if isinstance(fact, TicketFact) else None
        return [] if age is None else [sum(age > limit for limit in AGE_LIMITS)]
    return [_bucket(fact.day, dimension)]


def _bucket(day: date, dimension: Dimension) -> date:
    if dimension == "week":
        return day - timedelta(days=day.weekday())
    if dimension == "month":
        return day.replace(day=1)
    return day


def bucket_end(start: date, dimension: Dimension) -> date:
    """O último dia de um período de TIMES que começa em `start`."""
    if dimension == "week":
        return start + timedelta(days=6)
    if dimension == "month":
        return _month(start)[1]
    return start


def _label(data: Facts, dimension: Dimension, key: Key) -> str | None:
    if not isinstance(key, int) or dimension == "age":
        return None
    if dimension == "person":
        return data.users[key].display_name
    if dimension == "client":
        return data.clients[key].label
    if dimension == "team":
        return data.teams[key].name
    return data.statuses[key].name


def run(
    data: Facts, block: Block, start: date, end: date, *, dimension: Dimension | None = None
) -> Result:
    """Calcula um bloco. `dimension` troca a do bloco (a tela agrupa por semana um gráfico por
    dia de um período longo)."""
    if block.visual == "tasks":
        return Result(
            dimension=None,
            is_list=True,
            tasks=[t for t in data.tasks if t.overtime or not block.only_overtime],
        )
    dim = dimension or block.dimension
    measures = block.measures
    contributions = {m: _contributions(data, m) for m in measures}
    total = {m: _reduce(m, [amount for _, amount in contributions[m]]) for m in measures}
    if dim is None:
        return Result(dimension=None, total=total)

    amounts: dict[Key, dict[Measure, list[int]]] = defaultdict(lambda: {m: [] for m in measures})
    if dim in TIMES:  # todos os períodos, mesmo os vazios, já na ordem
        bucket = _bucket(start, dim)
        while bucket <= end:
            amounts[bucket] = {m: [] for m in measures}
            bucket = _bucket(bucket + timedelta(days={"day": 1, "week": 7}.get(dim, 32)), dim)
    elif dim == "age":  # as quatro faixas, na ordem
        for band in range(len(AGE_LIMITS) + 1):
            amounts[band] = {m: [] for m in measures}
    for m in measures:
        for fact, amount in contributions[m]:
            for key in _keys(fact, dim):
                amounts[key][m].append(amount)

    def reduced(lists: dict[Measure, list[int]]) -> dict[Measure, Value]:
        return {m: _reduce(m, lists[m]) for m in measures}

    rows = [Row(key, _label(data, dim, key), reduced(lists)) for key, lists in amounts.items()]
    if dim in TIMES or dim == "age":
        return Result(dimension=dim, rows=rows, total=total)

    def by_name(r: Row) -> tuple[bool, str]:
        return r.label is None, (r.label or "").casefold()

    first = measures[0]
    if block.order == "name":
        rows.sort(key=by_name)
    else:
        sign = -1 if block.order == "desc" else 1
        rows.sort(key=lambda r: (sign * (r.values[first] or 0), *by_name(r)))
    if block.top and len(rows) > block.top:
        rest = {r.key for r in rows[block.top :]}
        others = {m: [a for k in rest for a in amounts[k][m]] for m in measures}
        rows = [*rows[: block.top], Row(OTHERS, None, reduced(others))]
    return Result(dimension=dim, rows=rows, total=total)
