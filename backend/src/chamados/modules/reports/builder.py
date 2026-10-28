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
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Literal, get_args

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from chamados.modules.reports.service import (
    MAX_DAYS,
    TZ,
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
from chamados.modules.system.work_hours import Calendar

Visual = Literal[
    "cards", "bars", "columns", "stacked", "line", "combo", "table", "tasks", "heatmap"
]
Dimension = Literal[
    "person",
    "client",
    "team",
    "status",
    "age",
    "day",
    "week",
    "month",
    "weekday",
    "hour",
    "weekday_hour",
]
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
    "overtime_rate",
    "hours_per_ticket",
    "completion_rate",
    "tasks_per_workday",
]
Order = Literal["desc", "asc", "name"]
# As colunas da lista de tarefas, na ordem em que aparecem: o chamado é o número e o título; o
# tempo e o fora do expediente, os minutos da tarefa.
TaskColumn = Literal["when", "person", "ticket", "client", "team", "status", "time", "overtime"]
TASK_COLUMNS: tuple[TaskColumn, ...] = get_args(TaskColumn)
# As de sempre na tela e no PDF; o CSV de sempre também tem o cliente.
DEFAULT_COLUMNS: tuple[TaskColumn, ...] = ("when", "person", "ticket", "time", "overtime")
CSV_COLUMNS: tuple[TaskColumn, ...] = ("when", "person", "ticket", "client", "time", "overtime")
# Comparar com nada, com o período imediatamente anterior ou com o mesmo período do ano anterior.
Compare = Literal["none", "previous", "year"]

VISUALS: tuple[Visual, ...] = (
    "cards",
    "bars",
    "columns",
    "stacked",
    "line",
    "combo",
    "table",
    "heatmap",
    "tasks",
)
DIMENSIONS: tuple[Dimension, ...] = (
    "person",
    "client",
    "team",
    "status",
    "age",
    "day",
    "week",
    "month",
    "weekday",
    "hour",
    "weekday_hour",
)
CATEGORIES: tuple[Dimension, ...] = ("person", "client", "team", "status")
TIMES: tuple[Dimension, ...] = ("day", "week", "month")
# O dia da semana (0 = segunda), a hora do dia (0 a 23) e os dois juntos (o mapa de calor: dia ×
# 24 + hora), no fuso da máquina: todos aparecem, na ordem, como os períodos; não detalham (não há
# filtro por dia da semana nem por hora).
CYCLES: tuple[Dimension, ...] = ("weekday", "hour", "weekday_hour")
CYCLE_SIZE: dict[Dimension, int] = {"weekday": 7, "hour": 24, "weekday_hour": 7 * 24}
MEASURES: tuple[Measure, ...] = (
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
    "overtime_rate",
    "hours_per_ticket",
    "completion_rate",
    "tasks_per_workday",
)
# Em minutos.
DURATIONS: tuple[Measure, ...] = (
    "hours",
    "overtime",
    "regular",
    "in_plan",
    "excess",
    "discounted",
    "charged",
    "hours_per_ticket",
)
ELAPSED: tuple[Measure, ...] = ("lead_time", "net_lead_time")  # minutos, pela mediana
# Em centésimos de ponto (1250 = 12,5%); a taxa de conclusão passa de 100% quando se conclui
# mais do que se registra.
PERCENT: tuple[Measure, ...] = ("reopen_rate", "overtime_rate", "completion_rate")
RATES: tuple[Measure, ...] = ("tasks_per_workday",)  # em centésimos (250 = 2,5 por dia)


def unit(measure: Measure) -> str:
    """A unidade de uma medida: as barras + linha só juntam duas da mesma, no mesmo eixo."""
    for name, group in (
        ("duration", DURATIONS),
        ("elapsed", ELAPSED),
        ("percent", PERCENT),
        ("rate", RATES),
    ):
        if measure in group:
            return name
    return "count"


# As medidas derivadas: uma conta entre duas somas que já existem (`service.Sums`), em cada
# linha e no total; sem base (o divisor zero), None. As horas no expediente (`regular`), as no
# plano do cliente (`in_plan`) e o excedente a cobrar (`charged`) são uma diferença: as horas
# menos as extras ou as excedentes, e as excedentes menos as descontadas (DIFFERENCES); as
# outras, uma divisão. As tarefas por dia
# útil dividem pelos dias do expediente no período (`workdays`), e por isso não se agrupam por
# período, dia da semana nem hora (o dia de folga daria divisão por zero).
DERIVED: dict[Measure, tuple[Summed, Summed | None]] = {
    "regular": ("hours", "overtime"),
    "in_plan": ("hours", "excess"),
    "charged": ("excess", "discounted"),
    "overtime_rate": ("overtime", "hours"),
    "hours_per_ticket": ("hours", "worked"),  # ÷ os chamados distintos com tarefa
    "completion_rate": ("closed", "opened"),
    "tasks_per_workday": ("tasks", None),
}
DIFFERENCES: tuple[Measure, ...] = ("regular", "in_plan", "charged")
# A direção boa de cada medida, para a cor da variação dos cartões: 1, subir é bom; -1, subir é
# ruim. As que não estão aqui são neutras (horas, tarefas, registrados e cancelados).
GOOD_DIRECTION: dict[Measure, int] = {
    "closed": 1,
    "completion_rate": 1,
    "overtime": -1,
    "overtime_rate": -1,
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
CHARTS: tuple[Visual, ...] = ("bars", "columns", "stacked", "line", "combo")
REFERENCED: tuple[Visual, ...] = ("columns", "line")  # com a linha de referência
# As cores das séries (os tokens da paleta, web/palette.py) que um bloco pode escolher, e os
# visuais de uma série só, que a usam (as empilhadas e as barras + linha já têm duas cores).
Series = Literal["chart-1", "chart-2", "chart-3", "chart-4"]
SERIES: tuple[Series, ...] = get_args(Series)
COLORED: tuple[Visual, ...] = ("bars", "columns", "line")
# Os que têm a altura escolhida (as barras crescem com as linhas, uma por valor).
SIZED: tuple[Visual, ...] = ("columns", "stacked", "line", "combo", "heatmap")
# Idade do em aberto no fim do período (§14.3): até 1 dia, 1 a 3, 3 a 7, mais de 7 (em minutos).
AGE_LIMITS = (24 * 60, 3 * 24 * 60, 7 * 24 * 60)
STACKED: list[Measure] = ["hours", "overtime"]  # no expediente (horas − extras) e extras
# As medidas sem a tendência dos cartões: o em aberto é o retrato do fim, e as tarefas por dia
# útil não se agrupam por período.
UNTRENDED: tuple[Measure, ...] = ("backlog", "tasks_per_workday")

# Períodos que andam com o calendário (os slugs também são os da URL da tela), na ordem do
# seletor. "ultimos-n-dias" leva o número de dias (`PeriodSpec.days`, `dias` na URL).
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
MAX_MODELS = 50


class PeriodSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Relative | Literal["personalizado"] = "mes-atual"
    start: date | None = None  # só no personalizado
    end: date | None = None
    days: int | None = Field(default=None, ge=1, le=MAX_DAYS)  # só nos últimos N dias
    compare: Compare = "none"  # os cartões mostram a variação sobre o período comparado


class FilterSpec(BaseModel):
    """Os filtros salvos: os mesmos de `service.resolve`, pelos ids públicos."""

    model_config = ConfigDict(extra="forbid")

    teams: list[uuid.UUID] = []
    people: list[uuid.UUID] = []
    clients: list[uuid.UUID] = []
    no_client: bool = False
    statuses: list[int] = []


class BlockPeriod(BaseModel):
    """O período próprio de um bloco: um relativo (com os N dias no "ultimos-n-dias"). Anda com o
    calendário."""

    model_config = ConfigDict(extra="forbid")

    kind: Relative
    days: int | None = Field(default=None, ge=1, le=MAX_DAYS)  # só nos últimos N dias


class Block(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visual: Visual
    title: str = Field(default="", max_length=120)  # vazio: o título automático
    dimension: Dimension | None = None
    measures: list[Measure] = Field(default=[], max_length=len(MEASURES))
    top: int | None = Field(default=None, ge=1, le=100)  # só os N maiores; o resto em "Outros"
    hide_others: bool = False  # com os N maiores, sem a linha "Outros"
    order: Order = "desc"
    only_overtime: bool = False  # lista de tarefas: só as que têm tempo fora do expediente
    # Os tempos até a conclusão pela mediana (§14.1) ou, escolhida no bloco, pela média, com o
    # nome dizendo qual é.
    aggregate: Literal["median", "mean"] = "median"
    area: bool = False  # linha: a área sob ela preenchida
    big: bool = False  # cartões com uma medida: o número grande, com a variação e a tendência
    # Colunas e linha: uma linha tracejada na média ou na mediana dos pontos (não é meta: §14.1).
    reference: Literal["none", "mean", "median"] = "none"
    # O período e o filtro próprios do bloco; None: os da tela. O filtro só restringe o da tela,
    # campo a campo (`narrow`).
    period: BlockPeriod | None = None
    filters: FilterSpec | None = None
    # Na grade da tela: None, a automática (`reports_blocks.wide`); meia linha ou a linha inteira.
    width: Literal["half", "full"] | None = None
    height: Literal["s", "m", "l"] = "m"  # colunas, linha e mapa de calor (SIZED)
    color: Series | None = None  # a cor da série nas barras, colunas e linha (None: `chart-1`)
    # O formato das horas (None: o do modelo, `ReportConfig.hours`) e as casas das horas em
    # decimal, das porcentagens e das taxas (None: as de sempre).
    hours: Literal["hm", "decimal"] | None = None
    decimals: Literal[0, 1, 2] | None = None
    # As colunas da lista de tarefas (None: as de sempre, DEFAULT_COLUMNS e, no CSV, CSV_COLUMNS),
    # sempre na ordem de TASK_COLUMNS.
    columns: list[TaskColumn] | None = Field(default=None, min_length=1)
    in_pdf: bool = True  # False: o bloco fica na tela e no CSV, mas sai do PDF


class PdfSpec(BaseModel):
    """O PDF de um modelo interno (§14.8.6): A4 em pé ou deitado, o título (vazio: o nome do
    modelo) e um texto livre no rodapé de cada página (vazio: só o "Gerado em…")."""

    model_config = ConfigDict(extra="forbid")

    orientation: Literal["portrait", "landscape"] = "portrait"
    title: str = Field(default="", max_length=120)
    footer: str = Field(default="", max_length=200)


# As colunas da lista de chamados do relatório para o cliente, nesta ordem. As horas são do
# `ClientSpec.show_hours` e quem atendeu, do `ReportConfig.show_people`. Uma lista fechada de
# dados do próprio chamado: nada de organização interna (§14.8.5, "Fica de fora").
ClientColumn = Literal["ticket", "title", "opened", "closed", "status"]
CLIENT_COLUMNS: tuple[ClientColumn, ...] = get_args(ClientColumn)


class ClientSpec(BaseModel):
    """O relatório para o cliente (§14.8.5): o texto de abertura e as observações do fim (livres,
    escritos no modelo), as colunas da lista (sempre na ordem de CLIENT_COLUMNS) e as horas (a
    coluna e o total)."""

    model_config = ConfigDict(extra="forbid")

    intro: str = Field(default="", max_length=1000)
    notes: str = Field(default="", max_length=1000)
    columns: list[ClientColumn] = Field(default=list(CLIENT_COLUMNS), min_length=1)
    show_hours: bool = True


class ReportConfig(BaseModel):
    """O que um modelo guarda (`report_models.config`). `version` muda quando o formato mudar
    de um jeito que os modelos salvos precisem ser convertidos (`upgrade`)."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[2] = 2
    # O que o modelo mostra, em uma frase: abaixo do título no PDF e na dica da aba.
    description: str = Field(default="", max_length=200)
    period: PeriodSpec = PeriodSpec()
    filters: FilterSpec = FilterSpec()
    hours: Literal["hm", "decimal"] = "hm"  # 7h30 ou 7,5 h
    # Para o cliente (§14.8.5): o PDF tem um formato fixo (totais e chamados) e os blocos não
    # aparecem; `show_people`, mostrar quem atendeu (os responsáveis).
    audience: Literal["internal", "client"] = "internal"
    show_people: bool = False
    client: ClientSpec = ClientSpec()
    pdf: PdfSpec = PdfSpec()
    blocks: list[Block] = Field(max_length=12)

    @model_validator(mode="after")
    def _has_blocks(self) -> "ReportConfig":
        if self.audience == "internal" and not self.blocks:
            raise ValueError("um modelo interno precisa de ao menos um bloco")
        return self


def upgrade(config: dict[str, Any]) -> dict[str, Any]:
    """A configuração salva num formato antigo, convertida para o atual (`ReportConfig`).
    1 → 2: `period.compare` era booleano (comparar com o período anterior ou não)."""
    if config.get("version", 1) == 1:
        period = dict(config.get("period") or {})
        if "compare" in period:
            period["compare"] = "previous" if period["compare"] else "none"
        config = {**config, "period": period, "version": 2}
    return config


FilterField = Literal["teams", "people", "clients", "statuses"]


def narrow(screen: FilterSpec, own: FilterSpec) -> tuple[FilterSpec, list[FilterField]]:
    """O filtro de um bloco sobre o da tela, campo a campo: com valores nos dois, a interseção;
    só num, esse. Devolve também os campos em que os dois têm valores e nada em comum (o bloco
    não consulta nada). O cliente e o "sem cliente" são um campo só (`None` é o sem cliente)."""
    conflicts: list[FilterField] = []

    def both[T](mine: list[T], theirs: list[T], name: FilterField) -> list[T]:
        if not (mine and theirs):
            return mine or theirs
        common = [v for v in mine if v in theirs]
        if not common:
            conflicts.append(name)
        return common

    clients = both(
        [*([None] if screen.no_client else []), *screen.clients],
        [*([None] if own.no_client else []), *own.clients],
        "clients",
    )
    result = FilterSpec(
        teams=both(screen.teams, own.teams, "teams"),
        people=both(screen.people, own.people, "people"),
        clients=[c for c in clients if c is not None],
        no_client=None in clients,
        statuses=both(screen.statuses, own.statuses, "statuses"),
    )
    return result, conflicts


_CARDS = Block(visual="cards", measures=["hours", "overtime", "tasks", "opened", "closed"])
_PLAN: list[Measure] = ["in_plan", "excess"]  # as horas no plano do cliente e as além dele
# As horas descontadas na tela e o excedente a cobrar (`with_discount`).
_DISCOUNT: list[Measure] = ["discounted", "charged"]

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
    """A aba Clientes com horas descontadas: o desconto e o excedente a cobrar logo depois das
    horas excedentes, nos blocos que as mostram."""

    def measures(block: Block) -> list[Measure]:
        return [n for m in block.measures for n in ([m, *_DISCOUNT] if m == "excess" else [m])]

    blocks = [b.model_copy(update={"measures": measures(b)}) for b in config.blocks]
    return config.model_copy(update={"blocks": blocks})


def dimensions_for(visual: Visual) -> tuple[Dimension, ...]:
    """Os agrupamentos de um visual: os que o editor oferece e o `check_block` aceita (um teste
    confere que os dois concordam). As barras agrupam por cadastro ou idade; a linha, só por
    período; a idade é do em aberto, que não tem horas para empilhar; cartões e a lista de
    tarefas não agrupam."""
    if visual in ("cards", "tasks"):
        return ()
    if visual == "heatmap":  # o dia da semana × a hora, e só ele
        return ("weekday_hour",)
    if visual == "combo":  # a linha liga pontos em ordem: períodos, dias da semana, horas
        return (*TIMES, "weekday", "hour")
    if visual == "bars":
        return (*CATEGORIES, "age")
    if visual == "line":
        return TIMES
    if visual == "stacked":
        return tuple(d for d in DIMENSIONS if d not in ("age", "weekday_hour"))
    return tuple(d for d in DIMENSIONS if d != "weekday_hour")


def measures_for(visual: Visual, dimension: Dimension | None) -> tuple[Measure, ...]:
    """As medidas que cabem num visual com o agrupamento (o editor oferece só estas): as
    empilhadas são sempre as horas e as extras; a idade é só do em aberto; o em aberto, retrato
    do fim, e as tarefas por dia útil não se agrupam por período, dia da semana nem hora."""
    if visual == "tasks":
        return ()
    if visual == "stacked":
        return tuple(STACKED)
    if dimension == "age":
        return ("backlog",)
    timed = dimension in (*TIMES, *CYCLES)
    return tuple(m for m in MEASURES if not (timed and m in ("backlog", "tasks_per_workday")))


def check_block(block: Block) -> None:
    """As combinações que o formulário não deixa escolher, conferidas de novo ao salvar."""
    if block.visual == "tasks":
        return
    if block.columns is not None:
        raise HTTPException(422, "As colunas valem na lista de tarefas.")
    if block.visual != "cards" and block.dimension is None:
        raise HTTPException(422, "Escolha o que agrupar.")
    if not block.measures:
        raise HTTPException(422, "Escolha ao menos uma medida.")
    if (
        (block.visual in CHARTS and block.visual not in ("stacked", "combo"))
        or block.visual == "heatmap"
    ) and len(block.measures) != 1:
        raise HTTPException(422, "Um gráfico mostra uma medida só.")
    if (block.visual == "heatmap") != (block.dimension == "weekday_hour"):
        raise HTTPException(422, "O mapa de calor cruza o dia da semana com a hora, e só ele.")
    if block.visual == "combo" and not (
        len(set(block.measures)) == len(block.measures) == 2
        and unit(block.measures[0]) == unit(block.measures[1])
    ):
        raise HTTPException(422, "As barras + linha mostram duas medidas da mesma unidade.")
    if block.visual == "combo" and block.dimension not in dimensions_for("combo"):
        raise HTTPException(
            422, "As barras + linha agrupam por dia, semana, mês, dia da semana ou hora."
        )
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
    if block.dimension in CYCLES and "backlog" in block.measures:
        raise HTTPException(
            422,
            "Em aberto é o retrato do fim do período: não se agrupa por dia da semana nem hora.",
        )
    if block.big and (block.visual != "cards" or len(block.measures) != 1):
        raise HTTPException(422, "O número grande é um cartão de uma medida só.")
    if block.area and block.visual != "line":
        raise HTTPException(422, "A área é uma opção da linha.")
    if block.reference != "none" and block.visual not in REFERENCED:
        raise HTTPException(422, "A linha de referência vale nas colunas e na linha.")
    if (block.top or block.hide_others) and block.dimension not in CATEGORIES:
        raise HTTPException(
            422, "Só os maiores vale ao agrupar por pessoa, cliente, grupo ou status."
        )
    if block.hide_others and not block.top:
        raise HTTPException(422, "Esconder Outros vale com só os maiores.")
    if block.color is not None and block.visual not in COLORED:
        raise HTTPException(422, "A cor vale nas barras, nas colunas e na linha.")
    if block.hours is not None and not set(block.measures) & {*DURATIONS}:
        raise HTTPException(422, "O formato das horas vale nas medidas de horas.")
    if block.decimals is not None and not set(block.measures) & {*DURATIONS, *PERCENT, *RATES}:
        raise HTTPException(422, "As casas decimais valem nas horas, nas porcentagens e nas taxas.")
    if block.height != "m" and block.visual not in SIZED:
        raise HTTPException(422, "A altura vale nas colunas, na linha e no mapa de calor.")
    if block.aggregate == "mean" and not set(block.measures) & set(ELAPSED):
        raise HTTPException(422, "A média só vale para os tempos até a conclusão.")
    if block.dimension in (*TIMES, *CYCLES) and "tasks_per_workday" in block.measures:
        raise HTTPException(
            422, "Tarefas por dia útil não se agrupa por período, dia da semana nem hora."
        )


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
    """O período com que se compara (`PeriodSpec.compare`); sem comparar, None."""
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

# id do cadastro, dia, faixa de idade, dia da semana, hora, OTHERS ou None (sem cliente)
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
    mean: bool = False  # os tempos até a conclusão pela média (`Block.aggregate`)
    cut: bool = False  # linhas de fora dos N maiores, sem "Outros" (o total continua com elas)
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


def _group(dimension: Dimension, summed: Summed | None = None) -> Group:
    """O agrupamento das somas de uma dimensão (menos a idade, que sai das linhas do em aberto):
    o dia serve à semana, ao mês e ao dia da semana; os chamados distintos (`worked`) não somam
    de um dia para o outro e têm o agrupamento de cada um."""
    if summed == "worked" or dimension not in (*TIMES, "weekday"):
        return dimension  # type: ignore[return-value]
    return "day"


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
            summed = [SUMS[m]] if m in SUMS else [c for c in DERIVED.get(m, ()) if c]
            for c in summed:
                groups = want.sums.setdefault(c, set())
                if dimension is not None:
                    groups.add(_group(dimension, c))
                    if c == "worked" and dimension == "day" and block.visual in CHARTS:
                        # Num período longo, a tela agrupa por semana o gráfico por dia
                        # (`reports_blocks.DAILY_LIMIT`), e o `worked` não sai do dia.
                        groups.add("week")
                elif block.visual == "cards" and m not in UNTRENDED:  # a tendência (`trend`)
                    # Por dia; num período longo, por semana (só o `worked` não sai do dia).
                    groups.update({"day", "week"} if c == "worked" else {"day"})
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


def _total(data: Facts, measure: Measure, *, mean: bool = False) -> Value:
    if measure in SUMS:
        return _sums(data, SUMS[measure], None).total
    return _reduce(measure, [amount for _, amount in _contributions(data, measure)], mean=mean)


def _amounts(data: Facts, measure: Measure, dimension: Dimension) -> Iterator[tuple[Key, int]]:
    """As parcelas de uma medida por chave da dimensão: as somas de cada chave (o dia, já no
    período da semana ou do mês) ou, na mediana e na porcentagem, o valor de cada concluído."""
    if dimension == "age":  # só o em aberto (check_block)
        _part(data, "backlog")
        for t in data.backlog:
            if t.age is not None:
                yield sum(t.age > limit for limit in AGE_LIMITS), 1
        return
    group = _group(dimension)

    def bucket(key: Key) -> Key:
        if isinstance(key, date):
            return key.weekday() if dimension == "weekday" else _bucket(key, dimension)
        return key

    if measure in SUMS:
        for key, amount in _sums(data, SUMS[measure], group).by[group].items():
            yield bucket(key), amount
        return
    for fact, amount in _contributions(data, measure):
        for key in group_keys(fact, group):
            yield bucket(key), amount


def _reduce(measure: Measure, amounts: list[int], *, mean: bool = False) -> Value:
    if measure in ELAPSED:
        if not amounts:
            return None
        return round(statistics.fmean(amounts) if mean else statistics.median(amounts))
    if measure in PERCENT:
        return round(statistics.fmean(amounts)) if amounts else None
    return sum(amounts)


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
    if not isinstance(key, int) or dimension in ("age", *CYCLES):
        return None
    if dimension == "person":
        return data.users[key].display_name
    if dimension == "client":
        return data.clients[key].label
    if dimension == "team":
        return data.teams[key].name
    return data.statuses[key].name


def workdays(start: date, end: date, cal: Calendar, user_id: int | None = None) -> int:
    """Os dias do expediente no período: os dias de trabalho que não são feriado, no expediente
    da pessoa (None: o da instalação)."""
    count = 0
    day = start
    while day <= end:
        count += cal.window(user_id, day) is not None
        day += timedelta(days=1)
    return count


def _derive(measure: Measure, sums: dict[Summed, int | None], days: int) -> Value:
    """Uma medida derivada (DERIVED) a partir das somas das partes; sem base, None."""
    top, below = DERIVED[measure]
    if measure in DIFFERENCES:
        first, second = sums[top], sums[below] if below else None
        return None if first is None or second is None else first - second
    bottom = days if below is None else sums[below]
    if not bottom or sums[top] is None:
        return None
    scale = 10000 if measure in PERCENT else 100 if measure in RATES else 1
    return round(sums[top] * scale / bottom)  # type: ignore[operator]


def _summed_amounts(data: Facts, summed: Summed, dimension: Dimension) -> Iterator[tuple[Key, int]]:
    """As somas de uma parte de medida derivada por chave da dimensão (como o `_amounts`)."""
    group = _group(dimension, summed)
    for key, amount in _sums(data, summed, group).by[group].items():
        if isinstance(key, date):
            key = key.weekday() if dimension == "weekday" else _bucket(key, dimension)
        yield key, amount


def trend(
    data: Facts, block: Block, start: date, end: date, dimension: Dimension
) -> dict[Measure, list[Value]]:
    """A tendência de cada medida de um bloco de cartões no período (a sparkline), por dia ou por
    semana, das mesmas somas e linhas dos totais. O em aberto e as tarefas por dia útil ficam de
    fora (UNTRENDED): não se agrupam por período."""
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
    mean = block.aggregate == "mean"
    plain = [m for m in measures if m not in DERIVED]
    parts = sorted({c for m in measures if m in DERIVED for c in DERIVED[m] if c})
    # Os dias úteis até hoje: o mês, a semana e o trimestre em curso vão até o último dia, e os
    # dias que ainda não chegaram não têm tarefa.
    last = min(end, datetime.now(TZ).date())
    per_workday = "tasks_per_workday" in measures
    days = workdays(start, last, data.calendar) if per_workday else 0

    def values(
        plain_values: dict[Measure, Value],
        part_sums: dict[Summed, int | None],
        key: Key = None,
    ) -> dict[Measure, Value]:
        # Por pessoa, os dias úteis do expediente dela; no total, em "Outros" e nos outros
        # agrupamentos, os da instalação.
        n = days
        if per_workday and dim == "person" and isinstance(key, int):
            n = workdays(start, last, data.calendar, key)
        return {m: _derive(m, part_sums, n) if m in DERIVED else plain_values[m] for m in measures}

    total = values(
        {m: _total(data, m, mean=mean) for m in plain},
        {c: _sums(data, c, None).total for c in parts},
    )
    if dim is None:
        return Result(dimension=None, total=total, mean=mean)

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
            bucket = _bucket(bucket + timedelta(days={"day": 1, "week": 7}.get(dim, 32)), dim)
    elif dim == "age":  # as quatro faixas, na ordem
        for band in range(len(AGE_LIMITS) + 1):
            amounts[band] = empty()
    elif dim in CYCLES:  # os 7 dias da semana, as 24 horas ou as 168 do mapa, na ordem
        for cycle in range(CYCLE_SIZE[dim]):
            amounts[cycle] = empty()
    for m in plain:
        for key, amount in _amounts(data, m, dim):
            amounts[key][m].append(amount)
    for c in parts:
        if c not in plain:
            for key, amount in _summed_amounts(data, c, dim):
                amounts[key][c].append(amount)

    def reduced(
        lists: dict[str, list[int]], key: Key = None, *, others: bool = False
    ) -> dict[Measure, Value]:
        # Em "Outros", os chamados distintos de cada linha não somam (um chamado pode estar em
        # duas): as horas por chamado ficam sem valor.
        part_sums: dict[Summed, int | None] = {
            c: None if others and c == "worked" else sum(lists[c]) for c in parts
        }
        return values({m: _reduce(m, lists[m], mean=mean) for m in plain}, part_sums, key)

    rows = [Row(key, _label(data, dim, key), reduced(lists, key)) for key, lists in amounts.items()]
    if dim in (*TIMES, *CYCLES) or dim == "age":
        return Result(dimension=dim, rows=rows, total=total, mean=mean)

    def by_name(r: Row) -> tuple[bool, str, int]:
        # O id desempata dois nomes iguais (as somas vêm do banco sem uma ordem própria).
        return r.label is None, (r.label or "").casefold(), r.key if isinstance(r.key, int) else 0

    first = measures[0]
    if block.order == "name":
        rows.sort(key=by_name)
    else:
        sign = -1 if block.order == "desc" else 1
        rows.sort(key=lambda r: (sign * (r.values[first] or 0), *by_name(r)))
    if block.top and len(rows) > block.top:
        if block.hide_others:
            return Result(dimension=dim, rows=rows[: block.top], total=total, mean=mean, cut=True)
        rest = {r.key for r in rows[block.top :]}
        others: dict[str, list[int]] = {
            slot: [a for k in rest for a in amounts[k][slot]] for slot in slots
        }
        rows = [*rows[: block.top], Row(OTHERS, None, reduced(others, others=True))]
    return Result(dimension=dim, rows=rows, total=total, mean=mean)
