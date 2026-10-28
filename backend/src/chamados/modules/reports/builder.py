"""Os blocos dos relatórios (docs/14 §14.8): as abas prontas, os períodos e o cálculo de cada
bloco a partir dos dados do período (`service.facts`).

Cada bloco é "agrupar por × medida × visual", de listas fechadas no código: nada vira SQL. As
medidas vêm das tarefas (horas, horas extras, tarefas) ou dos chamados (registrados, concluídos,
cancelados, em aberto no fim, tempo até a conclusão, reabertura); com o agrupamento por pessoa,
um chamado conta para cada responsável. As contagens e as horas somam; os
tempos até a conclusão são a mediana (§14.1) e a reabertura, a porcentagem dos concluídos.
"""

import statistics
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict

from chamados.modules.reports.service import (
    MAX_DAYS,
    Facts,
    Group,
    Part,
    Summed,
    Sums,
    TaskFact,
    TicketFact,
    Want,
    group_keys,
)

Visual = Literal["cards", "bars", "columns", "line", "table", "tasks"]
Dimension = Literal["person", "client", "team", "status", "age", "day", "week"]
Measure = Literal[
    "hours",
    "overtime",
    "regular",
    "in_plan",
    "excess",
    "discounted",
    "charged",
    "tasks",
    "opened",
    "closed",
    "canceled",
    "backlog",
    "lead_time",
    "net_lead_time",
    "reopen_rate",
]
# As colunas da lista de tarefas, na ordem em que aparecem: o chamado é o número e o título; o
# tempo e o fora do expediente, os minutos da tarefa.
TaskColumn = Literal["when", "person", "ticket", "client", "time", "overtime"]
# As da tela e do PDF; o CSV também tem o cliente.
DEFAULT_COLUMNS: tuple[TaskColumn, ...] = ("when", "person", "ticket", "time", "overtime")
CSV_COLUMNS: tuple[TaskColumn, ...] = ("when", "person", "ticket", "client", "time", "overtime")
# Comparar com nada, com o período imediatamente anterior ou com o mesmo período do ano anterior.
Compare = Literal["none", "previous", "year"]

CATEGORIES: tuple[Dimension, ...] = ("person", "client", "team", "status")
TIMES: tuple[Dimension, ...] = ("day", "week")
# Em minutos.
DURATIONS: tuple[Measure, ...] = (
    "hours",
    "overtime",
    "regular",
    "in_plan",
    "excess",
    "discounted",
    "charged",
)
ELAPSED: tuple[Measure, ...] = ("lead_time", "net_lead_time")  # minutos, pela mediana
PERCENT: tuple[Measure, ...] = ("reopen_rate",)  # em centésimos de ponto (1250 = 12,5%)

# As medidas derivadas: a diferença entre duas somas que já existem (`service.Sums`), em cada
# linha e no total: as horas no expediente (`regular`), as no plano do cliente (`in_plan`) e as
# a cobrar (`charged`) são as horas menos as extras, as excedentes ou as descontadas.
DERIVED: dict[Measure, tuple[Summed, Summed]] = {
    "regular": ("hours", "overtime"),
    "in_plan": ("hours", "excess"),
    "charged": ("hours", "discounted"),
}
# A direção boa de cada medida, para a cor da variação dos cartões: 1, subir é bom; -1, subir é
# ruim. As que não estão aqui são neutras (horas, tarefas, registrados e cancelados).
GOOD_DIRECTION: dict[Measure, int] = {
    "closed": 1,
    "overtime": -1,
    "backlog": -1,
    "lead_time": -1,
    "net_lead_time": -1,
    "reopen_rate": -1,
}
# Os chamados por trás de cada medida de chamado (a lista do "detalhar").
TICKET_SETS: dict[Measure, Part] = {
    "opened": "opened",
    "closed": "closed",
    "canceled": "canceled",
    "backlog": "backlog",
    "lead_time": "closed",
    "net_lead_time": "closed",
    "reopen_rate": "closed",
}
CHARTS: tuple[Visual, ...] = ("bars", "columns", "line")
# Idade do em aberto no fim do período (§14.3): até 1 dia, 1 a 3, 3 a 7, mais de 7 (em minutos).
AGE_LIMITS = (24 * 60, 3 * 24 * 60, 7 * 24 * 60)
# O em aberto é o retrato do fim: os cartões não têm a tendência dele.
UNTRENDED: tuple[Measure, ...] = ("backlog",)

# Períodos que andam com o calendário (os slugs também são os da URL da tela), na ordem do
# seletor. "ultimos-n-dias" leva o número de dias (`dias` na URL).
Relative = Literal[
    "semana-atual",
    "semana-anterior",
    "mes-atual",
    "mes-anterior",
    "ultimos-7-dias",
    "ultimos-30-dias",
    "ultimos-90-dias",
    "ultimos-n-dias",
    "trimestre-atual",
    "trimestre-anterior",
    "ano-ate-hoje",
    "ano-anterior",
    "ultimos-12-meses",
]
RELATIVE: tuple[Relative, ...] = get_args(Relative)
LAST_DAYS = "ultimos-n-dias"
DEFAULT_DAYS = 30  # o padrão da §14.2
CUSTOM = "personalizado"
OTHERS = "outros"  # a chave da linha que junta o que passou dos N maiores


class Block(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visual: Visual
    dimension: Dimension | None = None
    measures: list[Measure] = []
    top: int | None = None  # só os N maiores; o resto em "Outros"
    only_overtime: bool = False  # lista de tarefas: só as que têm tempo fora do expediente


class ReportConfig(BaseModel):
    """Uma aba pronta: os blocos, na ordem."""

    model_config = ConfigDict(extra="forbid")

    blocks: list[Block]


_CARDS = Block(visual="cards", measures=["hours", "overtime", "tasks", "opened", "closed"])
_PLAN: list[Measure] = ["in_plan", "excess"]  # as horas no plano do cliente e as além dele
# As horas descontadas na tela e as horas a cobrar (`with_discount`).
_DISCOUNT: list[Measure] = ["discounted", "charged"]

# As abas prontas (as telas da §14.7 e os indicadores de chamados da §14.3). Uma aba nova é
# escrita aqui.
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
    # Sem a hora extra: para o cliente, todo o tempo é de trabalho normal (CLIENTS_OVERTIME
    # separa as horas no expediente e as extras). As horas no plano do cliente e as excedentes,
    # sempre.
    "clientes": ReportConfig(
        blocks=[
            Block(visual="cards", measures=["hours", *_PLAN, "tasks", "opened", "closed"]),
            Block(visual="bars", dimension="client", measures=["hours"], top=10),
            Block(
                visual="table",
                dimension="client",
                measures=["hours", *_PLAN, "opened", "closed"],
            ),
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

# A aba Clientes com a hora extra separada (a escolha "Hora extra" da tela): as horas no
# expediente e as extras ao lado do total, nos cartões e na tabela (antes das do plano).
_SEPARATED: list[Measure] = ["hours", "regular", "overtime", *_PLAN]
CLIENTS_OVERTIME = ReportConfig(
    blocks=[
        Block(visual="cards", measures=[*_SEPARATED, "tasks", "opened", "closed"]),
        Block(visual="bars", dimension="client", measures=["hours"], top=10),
        Block(visual="table", dimension="client", measures=[*_SEPARATED, "opened", "closed"]),
    ]
)


def with_discount(config: ReportConfig) -> ReportConfig:
    """A aba Clientes com horas descontadas: o desconto e as horas a cobrar logo depois das
    horas, nos cartões e na tabela; nos gráficos, as horas a cobrar no lugar das horas."""

    def measures(block: Block) -> list[Measure]:
        if block.visual not in ("cards", "table"):
            return ["charged" if m == "hours" else m for m in block.measures]
        return [n for m in block.measures for n in ([m, *_DISCOUNT] if m == "hours" else [m])]

    blocks = [b.model_copy(update={"measures": measures(b)}) for b in config.blocks]
    return config.model_copy(update={"blocks": blocks})


def _quarter(day: date) -> tuple[date, date]:
    first = date(day.year, (day.month - 1) // 3 * 3 + 1, 1)
    after = date(first.year + (first.month == 10), (first.month + 2) % 12 + 1, 1)
    return first, after - timedelta(days=1)


def _month(day: date) -> tuple[date, date]:
    first = day.replace(day=1)
    return first, (first + timedelta(days=31)).replace(day=1) - timedelta(days=1)


def previous_period(start: date, end: date, *, year_to_date: bool = False) -> tuple[date, date]:
    """O período imediatamente anterior (comparar com o anterior): o ano até a
    data ("ano-ate-hoje"), com as mesmas datas do ano anterior; meses inteiros, com os meses de
    antes; os demais, com o mesmo número de dias logo antes."""
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


def _year_before(day: date) -> date:
    """O mesmo dia do ano anterior; o 29 de fevereiro vira 28."""
    if (day.month, day.day) == (2, 29):
        day -= timedelta(days=1)
    return day.replace(year=day.year - 1)


def year_before(start: date, end: date) -> tuple[date, date]:
    """O mesmo período do ano anterior: meses inteiros, os mesmos meses (fevereiro inteiro com
    fevereiro inteiro, de 28 ou 29 dias); semanas inteiras (de segunda a domingo), as 52 semanas
    antes, para cada dia cair no mesmo dia da semana; as demais, as mesmas datas. Com um 29 de
    fevereiro no ano anterior, as mesmas datas de um período de 366 dias dariam 367: o fim é
    cortado no limite de um período (MAX_DAYS)."""
    if start.day == 1 and (end + timedelta(days=1)).day == 1:
        return start.replace(year=start.year - 1), _month(date(end.year - 1, end.month, 1))[1]
    if start.weekday() == 0 and ((end - start).days + 1) % 7 == 0:
        return start - timedelta(weeks=52), end - timedelta(weeks=52)
    first = _year_before(start)
    return first, min(_year_before(end), first + timedelta(days=MAX_DAYS - 1))


def comparison_period(
    start: date, end: date, compare: Compare, *, year_to_date: bool = False
) -> tuple[date, date] | None:
    """O período com que se compara; sem comparar, None."""
    if compare == "previous":
        return previous_period(start, end, year_to_date=year_to_date)
    if compare == "year":
        return year_before(start, end)
    return None


def relative_period(slug: str, today: date, days: int | None = None) -> tuple[date, date]:
    """O início e o fim (incluído) de um período de RELATIVE. A semana (de segunda a domingo),
    o mês, o trimestre e os últimos 12 meses (o atual e os 11 anteriores) vão até o último dia,
    como os meses da lista da tela; os N dias terminam hoje. `days`: os dias do "ultimos-n-dias"
    (sem ele, DEFAULT_DAYS)."""
    if slug in ("semana-atual", "semana-anterior"):
        monday = today - timedelta(days=today.weekday() + (7 if slug == "semana-anterior" else 0))
        return monday, monday + timedelta(days=6)
    if slug == "ano-anterior":
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    if slug == "ultimos-12-meses":
        index = today.year * 12 + today.month - 1 - 11
        return date(index // 12, index % 12 + 1, 1), _month(today)[1]
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
    if slug == LAST_DAYS:
        count = days or DEFAULT_DAYS
    else:
        count = {"ultimos-7-dias": 7, "ultimos-30-dias": 30, "ultimos-90-dias": 90}[slug]
    return today - timedelta(days=count - 1), today


# --- cálculo ---------------------------------------------------------------------------------

# id do cadastro, dia, faixa de idade, OTHERS ou None (sem cliente)
Key = int | date | str | None
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


def matching(previous: Result, index: int, row: Row) -> Row | None:
    """A linha do período comparado que corresponde a `row` (a de número `index`): no tempo, a
    da mesma posição (1º dia com o 1º dia); nos cadastros, a do mesmo valor. "Outros" não tem
    (os maiores mudam)."""
    if row.key == OTHERS:
        return None
    if previous.dimension in TIMES:
        return previous.rows[index] if index < len(previous.rows) else None
    return next((r for r in previous.rows if r.key == row.key), None)


# As medidas que somam: vêm somadas pelo `service.facts` (`Sums`), no banco ou das linhas. As
# derivadas (DERIVED) usam as somas das partes delas.
SUMS: dict[Measure, Summed] = {
    "hours": "hours",
    "overtime": "overtime",
    "excess": "excess",
    "discounted": "discounted",
    "tasks": "tasks",
    "opened": "opened",
    "closed": "closed",
    "canceled": "canceled",
    "backlog": "backlog",
}


def _group(dimension: Dimension) -> Group:
    """O agrupamento das somas de uma dimensão (menos a idade, que sai das linhas do em aberto):
    a semana sai do dia."""
    return "day" if dimension == "week" else dimension  # type: ignore[return-value]


def needs(blocks: Iterable[Block]) -> Want:
    """O que os blocos pedem ao `service.facts`: as somas das medidas que somam, com os
    agrupamentos; e as linhas da lista de tarefas (todas, ou só as que podem ter hora extra), dos
    concluídos (a mediana e a reabertura; o histórico, no tempo líquido) e do em aberto."""
    want = Want()
    for block in blocks:
        if block.visual == "tasks":
            want.rows.add("overtime" if block.only_overtime else "tasks")
        dimension = block.dimension if block.dimension not in (None, "age") else None
        for m in block.measures:
            summed = [SUMS[m]] if m in SUMS else list(DERIVED.get(m, ()))
            for c in summed:
                groups = want.sums.setdefault(c, set())
                if dimension is not None:
                    groups.add(_group(dimension))
                elif block.visual == "cards" and m not in UNTRENDED:  # a tendência (`trend`)
                    groups.add("day")
            if not summed:
                want.rows.add("closed")
                if m == "net_lead_time":
                    want.rows.add("net_lead")
    return want


def _part(data: Facts, part: Part) -> None:
    """Uma parte que não foi pedida viria vazia, e o número sairia zero sem aviso."""
    if part not in data.parts:
        raise ValueError(f"service.facts sem a parte {part!r}: peça com builder.needs")


def _sums(data: Facts, summed: Summed, group: Group | None) -> Sums:
    """As somas de uma medida, com o agrupamento pedido (o mesmo aviso do `_part`)."""
    sums = data.sums.get(summed)
    if sums is None or (group is not None and group not in sums.by):
        raise ValueError(
            f"service.facts sem a soma {summed!r} por {group!r}: peça com builder.needs"
        )
    return sums


def tickets_of(data: Facts, measure: Measure) -> list[TicketFact]:
    """Os chamados por trás de uma medida de chamado."""
    _part(data, TICKET_SETS[measure])
    return list(getattr(data, TICKET_SETS[measure]))


def _contributions(data: Facts, measure: Measure) -> list[tuple[TicketFact, int]]:
    """As medidas que não somam (a mediana e a porcentagem), das linhas dos concluídos."""
    _part(data, "closed")
    if measure == "lead_time":
        return [(t, t.lead) for t in data.closed if t.lead is not None]
    if measure == "net_lead_time":
        _part(data, "net_lead")
        return [(t, t.net_lead) for t in data.closed if t.net_lead is not None]
    return [(t, 10000 if t.reopened else 0) for t in data.closed]


def _total(data: Facts, measure: Measure) -> Value:
    if measure in SUMS:
        return _sums(data, SUMS[measure], None).total
    return _reduce(measure, [amount for _, amount in _contributions(data, measure)])


def _amounts(data: Facts, measure: Measure, dimension: Dimension) -> Iterator[tuple[Key, int]]:
    """As parcelas de uma medida por chave da dimensão: as somas de cada chave (o dia, já no
    período da semana) ou, na mediana e na porcentagem, o valor de cada concluído."""
    if dimension == "age":  # só o em aberto
        _part(data, "backlog")
        for t in data.backlog:
            if t.age is not None:
                yield sum(t.age > limit for limit in AGE_LIMITS), 1
        return
    group = _group(dimension)

    def bucket(key: Key) -> Key:
        return _bucket(key, dimension) if isinstance(key, date) else key

    if measure in SUMS:
        for key, amount in _sums(data, SUMS[measure], group).by[group].items():
            yield bucket(key), amount
        return
    for fact, amount in _contributions(data, measure):
        for key in group_keys(fact, group):
            yield bucket(key), amount


def _reduce(measure: Measure, amounts: list[int]) -> Value:
    if measure in ELAPSED:
        return round(statistics.median(amounts)) if amounts else None
    if measure in PERCENT:
        return round(statistics.fmean(amounts)) if amounts else None
    return sum(amounts)


def _bucket(day: date, dimension: Dimension) -> date:
    return day - timedelta(days=day.weekday()) if dimension == "week" else day


def bucket_end(start: date, dimension: Dimension) -> date:
    """O último dia de um período de TIMES que começa em `start`."""
    return start + timedelta(days=6) if dimension == "week" else start


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


def _derive(measure: Measure, sums: dict[Summed, int | None]) -> Value:
    """Uma medida derivada (DERIVED): a diferença das somas das partes; sem uma delas, None."""
    first, second = (sums[c] for c in DERIVED[measure])
    return None if first is None or second is None else first - second


def _summed_amounts(data: Facts, summed: Summed, dimension: Dimension) -> Iterator[tuple[Key, int]]:
    """As somas de uma parte de medida derivada por chave da dimensão (como o `_amounts`)."""
    group = _group(dimension)
    for key, amount in _sums(data, summed, group).by[group].items():
        yield (_bucket(key, dimension) if isinstance(key, date) else key), amount


def trend(
    data: Facts, block: Block, start: date, end: date, dimension: Dimension
) -> dict[Measure, list[Value]]:
    """A tendência de cada medida de um bloco de cartões no período (a sparkline), por dia ou por
    semana, das mesmas somas e linhas dos totais. O em aberto fica de fora (UNTRENDED): não se
    agrupa por período."""
    measures = [m for m in block.measures if m not in UNTRENDED]
    if not measures:
        return {}
    by_time = block.model_copy(update={"measures": measures})
    result = run(data, by_time, start, end, dimension=dimension)
    return {m: [r.values[m] for r in result.rows] for m in measures}


def run(
    data: Facts, block: Block, start: date, end: date, *, dimension: Dimension | None = None
) -> Result:
    """Calcula um bloco. `dimension` troca a do bloco (a tela agrupa por semana um gráfico por
    dia de um período longo). As medidas derivadas saem das somas das partes delas, em cada linha
    e no total."""
    if block.visual == "tasks":
        if block.only_overtime:
            _part(data, "overtime")
            tasks = [t for t in data.overtime_tasks if t.overtime]
        else:
            _part(data, "tasks")
            tasks = list(data.tasks)
        return Result(dimension=None, is_list=True, tasks=tasks)
    dim = dimension or block.dimension
    measures = block.measures
    plain = [m for m in measures if m not in DERIVED]
    parts = sorted({c for m in measures if m in DERIVED for c in DERIVED[m]})

    def values(
        plain_values: dict[Measure, Value], part_sums: dict[Summed, int | None]
    ) -> dict[Measure, Value]:
        return {m: _derive(m, part_sums) if m in DERIVED else plain_values[m] for m in measures}

    total = values(
        {m: _total(data, m) for m in plain},
        {c: _sums(data, c, None).total for c in parts},
    )
    if dim is None:
        return Result(dimension=None, total=total)

    # As parcelas de cada chave: as das medidas e as das partes das derivadas (os nomes que
    # coincidem, como "hours", são a mesma soma).
    slots = [*plain, *(c for c in parts if c not in plain)]

    def empty() -> dict[str, list[int]]:
        return {slot: [] for slot in slots}

    amounts: dict[Key, dict[str, list[int]]] = defaultdict(empty)
    if dim in TIMES:  # todos os períodos, mesmo os vazios, já na ordem
        bucket = _bucket(start, dim)
        while bucket <= end:
            amounts[bucket] = empty()
            bucket += timedelta(days=7 if dim == "week" else 1)
    elif dim == "age":  # as quatro faixas, na ordem
        for band in range(len(AGE_LIMITS) + 1):
            amounts[band] = empty()
    for m in plain:
        for key, amount in _amounts(data, m, dim):
            amounts[key][m].append(amount)
    for c in parts:
        if c not in plain:
            for key, amount in _summed_amounts(data, c, dim):
                amounts[key][c].append(amount)

    def reduced(lists: dict[str, list[int]]) -> dict[Measure, Value]:
        part_sums: dict[Summed, int | None] = {c: sum(lists[c]) for c in parts}
        return values({m: _reduce(m, lists[m]) for m in plain}, part_sums)

    rows = [Row(key, _label(data, dim, key), reduced(lists)) for key, lists in amounts.items()]
    if dim in TIMES or dim == "age":
        return Result(dimension=dim, rows=rows, total=total)

    def by_name(r: Row) -> tuple[bool, str, int]:
        # O id desempata dois nomes iguais (as somas vêm do banco sem uma ordem própria).
        return r.label is None, (r.label or "").casefold(), r.key if isinstance(r.key, int) else 0

    # Do maior para o menor, pela primeira medida.
    first = measures[0]
    rows.sort(key=lambda r: (-(r.values[first] or 0), *by_name(r)))
    if block.top and len(rows) > block.top:
        rest = {r.key for r in rows[block.top :]}
        others: dict[str, list[int]] = {
            slot: [a for k in rest for a in amounts[k][slot]] for slot in slots
        }
        rows = [*rows[: block.top], Row(OTHERS, None, reduced(others))]
    return Result(dimension=dim, rows=rows, total=total)
