"""Construtor guiado dos relatórios (docs/14 §14.8): a configuração de um modelo (período,
filtros e blocos), os modelos prontos e o cálculo de cada bloco a partir dos dados do período
(`service.facts`).

Cada bloco é "agrupar por × medida × visual", escolhidos em listas fechadas: nada do que a pessoa
escolhe vira SQL. As medidas vêm das tarefas (horas, horas extras, tarefas) ou dos chamados
(registrados, concluídos); com o agrupamento por pessoa, um chamado conta para cada responsável.
"""

import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from chamados.modules.reports.service import Facts, TaskFact, TicketFact

Visual = Literal["cards", "bars", "columns", "line", "table", "tasks"]
Dimension = Literal["person", "client", "team", "status", "day", "week", "month"]
Measure = Literal["hours", "overtime", "tasks", "opened", "closed"]
Order = Literal["desc", "asc", "name"]

VISUALS: tuple[Visual, ...] = ("cards", "bars", "columns", "line", "table", "tasks")
DIMENSIONS: tuple[Dimension, ...] = ("person", "client", "team", "status", "day", "week", "month")
CATEGORIES: tuple[Dimension, ...] = ("person", "client", "team", "status")
TIMES: tuple[Dimension, ...] = ("day", "week", "month")
MEASURES: tuple[Measure, ...] = ("hours", "overtime", "tasks", "opened", "closed")
DURATIONS: tuple[Measure, ...] = ("hours", "overtime")  # em minutos; as outras são contagens
CHARTS: tuple[Visual, ...] = ("bars", "columns", "line")

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
    blocks: list[Block] = Field(min_length=1, max_length=12)


_CARDS = Block(visual="cards", measures=["hours", "overtime", "tasks", "opened", "closed"])

# Os modelos prontos (as telas da §14.7): não se apagam; duplicar leva os blocos.
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
}


def check_block(block: Block) -> None:
    """As combinações que o formulário não deixa escolher, conferidas de novo ao salvar."""
    if block.visual == "tasks":
        return
    if block.visual != "cards" and block.dimension is None:
        raise HTTPException(422, "Escolha o que agrupar.")
    if not block.measures:
        raise HTTPException(422, "Escolha ao menos uma medida.")
    if block.visual in CHARTS and len(block.measures) != 1:
        raise HTTPException(422, "Um gráfico mostra uma medida só.")
    if block.visual == "line" and block.dimension not in TIMES:
        raise HTTPException(422, "A linha agrupa por dia, semana ou mês.")
    if block.visual == "bars" and block.dimension not in CATEGORIES:
        raise HTTPException(422, "As barras agrupam por pessoa, cliente, grupo ou status.")


def _quarter(day: date) -> tuple[date, date]:
    first = date(day.year, (day.month - 1) // 3 * 3 + 1, 1)
    after = date(first.year + (first.month == 10), (first.month + 2) % 12 + 1, 1)
    return first, after - timedelta(days=1)


def _month(day: date) -> tuple[date, date]:
    first = day.replace(day=1)
    return first, (first + timedelta(days=31)).replace(day=1) - timedelta(days=1)


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

Key = int | date | str | None  # id do cadastro, dia, OTHERS ou None (sem cliente)


@dataclass
class Row:
    key: Key
    label: str | None  # nome do cadastro; None nos períodos e no "sem cliente" (a tela traduz)
    values: dict[Measure, int]


@dataclass
class Result:
    """Um bloco calculado. `rows` vem na ordem de exibição; `total` é o do período inteiro (um
    chamado com dois responsáveis conta uma vez, mesmo que apareça nas linhas dos dois)."""

    dimension: Dimension | None
    rows: list[Row] = field(default_factory=list)
    total: dict[Measure, int] = field(default_factory=dict)
    is_list: bool = False  # a lista de tarefas (`tasks`), sem agrupar
    tasks: list[TaskFact] = field(default_factory=list)


def _contributions(data: Facts, measure: Measure) -> Iterable[tuple[TaskFact | TicketFact, int]]:
    if measure == "hours":
        return ((t, t.minutes) for t in data.tasks)
    if measure == "overtime":
        return ((t, t.overtime) for t in data.tasks)
    if measure == "tasks":
        return ((t, 1) for t in data.tasks)
    return ((t, 1) for t in (data.opened if measure == "opened" else data.closed))


def _keys(fact: TaskFact | TicketFact, dimension: Dimension) -> Iterable[Key]:
    if dimension == "person":
        return [fact.author_id] if isinstance(fact, TaskFact) else fact.people
    if dimension == "client":
        return [fact.client_id]
    if dimension == "team":
        return [fact.team_id]
    if dimension == "status":
        return [fact.status_id]
    return [_bucket(fact.day, dimension)]


def _bucket(day: date, dimension: Dimension) -> date:
    if dimension == "week":
        return day - timedelta(days=day.weekday())
    if dimension == "month":
        return day.replace(day=1)
    return day


def _label(data: Facts, dimension: Dimension, key: Key) -> str | None:
    if not isinstance(key, int):
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
    total = {m: sum(amount for _, amount in _contributions(data, m)) for m in measures}
    if dim is None:
        return Result(dimension=None, total=total)

    values: dict[Key, dict[Measure, int]] = defaultdict(lambda: dict.fromkeys(measures, 0))
    if dim in TIMES:  # todos os períodos, mesmo os vazios, já na ordem
        bucket = _bucket(start, dim)
        while bucket <= end:
            values[bucket] = dict.fromkeys(measures, 0)
            bucket = _bucket(bucket + timedelta(days={"day": 1, "week": 7}.get(dim, 32)), dim)
    for m in measures:
        for fact, amount in _contributions(data, m):
            for key in _keys(fact, dim):
                values[key][m] += amount
    rows = [Row(key, _label(data, dim, key), v) for key, v in values.items()]
    if dim in TIMES:
        return Result(dimension=dim, rows=rows, total=total)

    def by_name(r: Row) -> tuple[bool, str]:
        return r.label is None, (r.label or "").casefold()

    first = measures[0]
    if block.order == "name":
        rows.sort(key=by_name)
    else:
        sign = -1 if block.order == "desc" else 1
        rows.sort(key=lambda r: (sign * r.values[first], *by_name(r)))
    if block.top and len(rows) > block.top:
        rest = rows[block.top :]
        others = {m: sum(r.values[m] for r in rest) for m in measures}
        rows = [*rows[: block.top], Row(OTHERS, None, others)]
    return Result(dimension=dim, rows=rows, total=total)
