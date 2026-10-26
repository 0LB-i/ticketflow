"""Construtor guiado dos relatórios (docs/14 §14.8): o cálculo de cada bloco a partir dos dados do
período, as combinações recusadas, os períodos relativos e o CSV de um bloco. Sem banco: os
dados (`service.Facts`) são montados à mão.
"""

import csv
import io
import uuid
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any, get_args

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from chamados.modules.catalog.models import TicketStatus
from chamados.modules.reports import csv_export
from chamados.modules.reports.builder import (
    BUILTINS,
    DIMENSIONS,
    MEASURES,
    OTHERS,
    STACKED,
    VISUALS,
    Block,
    PeriodSpec,
    check_block,
    comparison_period,
    dimensions_for,
    measures_for,
    needs,
    next_period,
    previous_period,
    relative_period,
    run,
    trend,
    upgrade,
    year_before,
)
from chamados.modules.reports.models import ReportModel
from chamados.modules.reports.saved import config_of
from chamados.modules.reports.service import (
    GROUPS,
    TZ,
    ClientName,
    Facts,
    Part,
    Summed,
    Sums,
    TaskFact,
    TeamName,
    TicketFact,
    UserName,
    add_up,
    net_minutes,
)
from chamados.modules.system.work_hours import DEFAULT

ANA, BIA = 1, 2
PADARIA, MERCADO, FARMACIA = 10, 11, 12
TI = 5
PENDENTE = 1
INICIO, FIM = date(2026, 10, 1), date(2026, 10, 20)


def _tarefa(
    autor: int, minutos: int, dia: date, *, extra: int = 0, cliente: int | None = None
) -> TaskFact:
    return TaskFact(
        author_id=autor,
        minutes=minutos,
        overtime=extra,
        done_at=datetime.combine(dia, datetime.min.time(), TZ) + timedelta(hours=10),
        ticket_number=1000,
        ticket_title="Impressora",
        client_id=cliente,
        team_id=TI,
        status_id=PENDENTE,
    )


def _chamado(
    dia: date, pessoas: set[int], cliente: int | None = None, numero: int = 1000, **extra: Any
) -> TicketFact:
    return TicketFact(
        number=numero,
        title="Impressora",
        client_id=cliente,
        team_id=TI,
        status_id=PENDENTE,
        day=dia,
        people=pessoas,
        created_at=datetime.combine(dia, datetime.min.time(), TZ),
        **extra,
    )


def _dados(
    tarefas: list[TaskFact],
    registrados: list[TicketFact] | None = None,
    concluidos: list[TicketFact] | None = None,
    cancelados: list[TicketFact] | None = None,
    em_aberto: list[TicketFact] | None = None,
) -> Facts:
    chamados = {
        "opened": registrados or [],
        "closed": concluidos or [],
        "canceled": cancelados or [],
        "backlog": em_aberto or [],
    }
    # As somas pelo mesmo caminho do `facts` quando as linhas vieram (`add_up`), em todos os
    # agrupamentos.
    somas: dict[Summed, Sums] = {
        "hours": add_up(((t, t.minutes) for t in tarefas), GROUPS),
        "overtime": add_up(((t, t.overtime) for t in tarefas), GROUPS),
        "tasks": add_up(((t, 1) for t in tarefas), GROUPS),
    }
    for parte, linhas in chamados.items():
        somas[parte] = add_up(((t, 1) for t in linhas), GROUPS)  # type: ignore[index]
    return Facts(
        parts=frozenset(get_args(Part)),
        work_hours=DEFAULT,
        tasks=tarefas,
        overtime_tasks=tarefas,
        opened=chamados["opened"],
        closed=chamados["closed"],
        canceled=chamados["canceled"],
        backlog=chamados["backlog"],
        sums=somas,
        users={ANA: UserName(uuid.uuid4(), "Ana"), BIA: UserName(uuid.uuid4(), "Bia")},
        clients={
            PADARIA: ClientName(uuid.uuid4(), "Padaria"),
            MERCADO: ClientName(uuid.uuid4(), "Mercado"),
            FARMACIA: ClientName(uuid.uuid4(), "=Farmácia"),
        },
        teams={TI: TeamName(uuid.uuid4(), "TI")},
        statuses={PENDENTE: TicketStatus(id=PENDENTE, name="Pendente")},
    )


def test_por_pessoa_com_tarefas_e_chamados() -> None:
    dados = _dados(
        [_tarefa(ANA, 60, INICIO, extra=30), _tarefa(BIA, 30, INICIO)],
        registrados=[_chamado(INICIO, {ANA})],
        concluidos=[_chamado(INICIO, {ANA, BIA})],
    )
    bloco = Block(
        visual="table", dimension="person", measures=["hours", "overtime", "tasks", "closed"]
    )
    r = run(dados, bloco, INICIO, FIM)
    assert [(x.label, x.values) for x in r.rows] == [
        ("Ana", {"hours": 60, "overtime": 30, "tasks": 1, "closed": 1}),
        ("Bia", {"hours": 30, "overtime": 0, "tasks": 1, "closed": 1}),
    ]
    # O chamado dos dois conta uma vez no total.
    assert r.total == {"hours": 90, "overtime": 30, "tasks": 2, "closed": 1}
    cartoes = run(dados, Block(visual="cards", measures=["opened", "closed"]), INICIO, FIM)
    assert cartoes.rows == [] and cartoes.total == {"opened": 1, "closed": 1}


def test_tendencia_dos_cartoes() -> None:
    """A sparkline de cada cartão: a medida por dia (ou semana), das mesmas somas e linhas dos
    totais; o em aberto (o retrato do fim) fica de fora."""
    segundo = INICIO + timedelta(days=1)
    dados = _dados(
        [_tarefa(ANA, 60, INICIO), _tarefa(BIA, 30, segundo), _tarefa(ANA, 15, segundo)],
        concluidos=[_chamado(segundo, {ANA}, lead=120)],
    )
    bloco = Block(visual="cards", measures=["hours", "closed", "lead_time", "backlog"])
    serie = trend(dados, bloco, INICIO, segundo, "day")
    assert serie["hours"] == [60, 45] and serie["closed"] == [0, 1]
    assert serie["lead_time"] == [None, 120]  # sem concluídos no dia, sem base
    assert "backlog" not in serie
    assert trend(dados, Block(visual="cards", measures=["backlog"]), INICIO, FIM, "day") == {}


def test_cada_bloco_pede_so_o_que_usa() -> None:
    """`service.facts` só consulta o que os blocos usam: as somas das medidas que somam, por
    agrupamento (o dia serve à semana e ao mês; nos cartões, à tendência, menos no em aberto), e
    as linhas da lista, dos concluídos (a mediana) e do em aberto. Uma parte ou uma soma que não
    veio é erro (não um zero)."""
    produtividade = needs(BUILTINS["produtividade"].blocks)
    assert produtividade.rows == set()
    assert produtividade.sums == {
        "hours": {"day", "person"},
        "overtime": {"day", "person"},
        "tasks": {"day", "person"},
        "opened": {"day"},
        "closed": {"day", "person"},
    }
    chamados = needs(BUILTINS["chamados"].blocks)
    assert chamados.rows == {"closed", "net_lead"}
    assert chamados.sums == {
        "opened": {"day", "team"},
        "closed": {"day", "team"},
        "canceled": {"day", "team"},
        "backlog": {"status", "team"},
    }
    assert needs([Block(visual="tasks", only_overtime=True)]).rows == {"overtime"}
    assert needs([Block(visual="tasks")]).rows == {"tasks"}
    assert needs([Block(visual="cards", measures=["lead_time"])]).rows == {"closed"}
    dados = replace(_dados([]), sums={})
    with pytest.raises(ValueError, match="closed"):
        run(dados, Block(visual="cards", measures=["closed"]), INICIO, INICIO)
    somente_total: dict[Summed, Sums] = {"hours": Sums(total=0)}
    dados = replace(_dados([]), sums=somente_total)
    with pytest.raises(ValueError, match="'hours' por 'person'"):
        bloco = Block(visual="table", dimension="person", measures=["hours"])
        run(dados, bloco, INICIO, INICIO)
    dados = replace(_dados([]), parts=frozenset({"closed"}))
    with pytest.raises(ValueError, match="net_lead"):
        run(dados, Block(visual="cards", measures=["net_lead_time"]), INICIO, INICIO)


def test_os_maiores_outros_e_ordem() -> None:
    dados = _dados(
        [
            _tarefa(ANA, 10, INICIO, cliente=PADARIA),
            _tarefa(ANA, 30, INICIO, cliente=MERCADO),
            _tarefa(ANA, 20, INICIO, cliente=FARMACIA),
            _tarefa(ANA, 5, INICIO),  # sem cliente
        ]
    )

    def linhas(**opcoes: object) -> list[tuple[object, int | None]]:
        bloco = Block(visual="table", dimension="client", measures=["hours"], **opcoes)
        return [(x.label or x.key, x.values["hours"]) for x in run(dados, bloco, INICIO, FIM).rows]

    assert linhas() == [("Mercado", 30), ("=Farmácia", 20), ("Padaria", 10), (None, 5)]
    assert linhas(top=2) == [("Mercado", 30), ("=Farmácia", 20), (OTHERS, 15)]
    assert linhas(order="asc") == [(None, 5), ("Padaria", 10), ("=Farmácia", 20), ("Mercado", 30)]
    # Por nome, "sem cliente" por último.
    assert linhas(order="name") == [("=Farmácia", 20), ("Mercado", 30), ("Padaria", 10), (None, 5)]


def test_periodos_vazios_entram_na_serie() -> None:
    dados = _dados([_tarefa(ANA, 60, date(2026, 10, 6)), _tarefa(ANA, 30, date(2026, 10, 7))])
    semanas = run(dados, Block(visual="line", dimension="week", measures=["hours"]), INICIO, FIM)
    # De segunda a segunda: a primeira semana começa antes do período.
    assert [(x.key, x.values["hours"]) for x in semanas.rows] == [
        (date(2026, 9, 28), 0),
        (date(2026, 10, 5), 90),
        (date(2026, 10, 12), 0),
        (date(2026, 10, 19), 0),
    ]
    dias = run(dados, Block(visual="columns", dimension="day", measures=["hours"]), INICIO, FIM)
    assert len(dias.rows) == 20 and dias.rows[5].values == {"hours": 60}
    meses = run(
        dados,
        Block(visual="columns", dimension="month", measures=["tasks"]),
        date(2026, 9, 15),
        date(2026, 11, 2),
    )
    assert [(x.key, x.values["tasks"]) for x in meses.rows] == [
        (date(2026, 9, 1), 0),
        (date(2026, 10, 1), 2),
        (date(2026, 11, 1), 0),
    ]
    # A tela troca o agrupamento por dia de um período longo.
    trocado = run(
        dados,
        Block(visual="columns", dimension="day", measures=["hours"]),
        INICIO,
        FIM,
        dimension="week",
    )
    assert trocado.dimension == "week" and len(trocado.rows) == 4


def test_lista_de_tarefas() -> None:
    dados = _dados([_tarefa(ANA, 60, INICIO, extra=30), _tarefa(BIA, 30, INICIO)])
    assert len(run(dados, Block(visual="tasks"), INICIO, FIM).tasks) == 2
    so_extras = run(dados, Block(visual="tasks", only_overtime=True), INICIO, FIM)
    assert so_extras.is_list and [t.author_id for t in so_extras.tasks] == [ANA]


@pytest.mark.parametrize(
    ("bloco", "erro"),
    [
        (Block(visual="table", dimension="person"), "Escolha ao menos uma medida."),
        (Block(visual="table", measures=["hours"]), "Escolha o que agrupar."),
        (
            Block(visual="bars", dimension="person", measures=["hours", "tasks"]),
            "Um gráfico mostra uma medida só.",
        ),
        (
            Block(visual="line", dimension="person", measures=["hours"]),
            "A linha agrupa por dia, semana ou mês.",
        ),
        (
            Block(visual="bars", dimension="day", measures=["hours"]),
            "As barras agrupam por pessoa, cliente, grupo, status ou idade.",
        ),
        (
            Block(visual="stacked", dimension="day", measures=["hours"]),
            "As colunas empilhadas mostram as horas no expediente e as extras.",
        ),
        (
            Block(visual="bars", dimension="age", measures=["opened"]),
            "A idade só vale para a medida Em aberto.",
        ),
        (
            Block(visual="line", dimension="week", measures=["backlog"]),
            "Em aberto é o retrato do fim do período: não se agrupa por dia, semana ou mês.",
        ),
    ],
)
def test_combinacoes_recusadas(bloco: Block, erro: str) -> None:
    with pytest.raises(HTTPException) as exc:
        check_block(bloco)
    assert exc.value.status_code == 422 and exc.value.detail == erro


def test_o_editor_oferece_so_o_que_o_check_block_aceita() -> None:
    # Cada visual × agrupamento × medida: o que `dimensions_for` e `measures_for` oferecem passa
    # no `check_block`; um agrupamento que eles não oferecem é recusado.
    for visual in VISUALS:
        if visual == "tasks":
            continue
        allowed = dimensions_for(visual)
        for dimension in (None, *DIMENSIONS):
            offered = dimension in allowed or (visual == "cards" and dimension is None)
            if visual == "cards" and dimension is not None:
                continue
            for measures in [STACKED] if visual == "stacked" else [[m] for m in MEASURES]:
                bloco = Block(visual=visual, dimension=dimension, measures=measures)
                if offered and set(measures) <= set(measures_for(visual, dimension)):
                    check_block(bloco)
                else:
                    with pytest.raises(HTTPException):
                        check_block(bloco)


def test_modelos_prontos_sao_validos() -> None:
    for config in BUILTINS.values():
        for bloco in config.blocks:
            check_block(bloco)
    check_block(Block(visual="stacked", dimension="client", measures=["hours", "overtime"]))


def test_periodos_relativos() -> None:
    hoje = date(2026, 11, 15)
    assert relative_period("mes-atual", hoje) == (date(2026, 11, 1), date(2026, 11, 30))
    assert relative_period("mes-anterior", hoje) == (date(2026, 10, 1), date(2026, 10, 31))
    assert relative_period("ultimos-7-dias", hoje) == (date(2026, 11, 9), hoje)
    assert relative_period("ultimos-30-dias", hoje) == (hoje - timedelta(days=29), hoje)
    assert relative_period("ultimos-90-dias", hoje) == (hoje - timedelta(days=89), hoje)
    assert relative_period("trimestre-atual", hoje) == (date(2026, 10, 1), date(2026, 12, 31))
    assert relative_period("trimestre-anterior", hoje) == (date(2026, 7, 1), date(2026, 9, 30))
    assert relative_period("ano-ate-hoje", hoje) == (date(2026, 1, 1), hoje)
    assert relative_period("trimestre-anterior", date(2027, 1, 10)) == (
        date(2026, 10, 1),
        date(2026, 12, 31),
    )
    assert relative_period("mes-anterior", date(2027, 1, 31)) == (
        date(2026, 12, 1),
        date(2026, 12, 31),
    )


def test_periodos_relativos_de_semana_ano_e_n_dias() -> None:
    domingo = date(2026, 11, 15)
    # A semana vai de segunda a domingo, inteira, como o mês.
    assert relative_period("semana-atual", domingo) == (date(2026, 11, 9), domingo)
    assert relative_period("semana-atual", date(2026, 11, 9)) == (
        date(2026, 11, 9),
        date(2026, 11, 15),
    )
    assert relative_period("semana-anterior", domingo) == (date(2026, 11, 2), date(2026, 11, 8))
    assert relative_period("ano-anterior", domingo) == (date(2025, 1, 1), date(2025, 12, 31))
    # Os 12 meses: o atual e os 11 anteriores, inteiros (até 366 dias).
    assert relative_period("ultimos-12-meses", domingo) == (date(2025, 12, 1), date(2026, 11, 30))
    assert relative_period("ultimos-12-meses", date(2026, 12, 3)) == (
        date(2026, 1, 1),
        date(2026, 12, 31),
    )
    assert relative_period("ultimos-12-meses", date(2024, 2, 10)) == (
        date(2023, 3, 1),
        date(2024, 2, 29),
    )
    # Os N dias terminam hoje; sem N, os 30 do padrão.
    assert relative_period("ultimos-n-dias", domingo, 1) == (domingo, domingo)
    assert relative_period("ultimos-n-dias", domingo, 45) == (date(2026, 10, 2), domingo)
    assert relative_period("ultimos-n-dias", domingo, 366) == (date(2025, 11, 15), domingo)
    assert relative_period("ultimos-n-dias", domingo) == relative_period("ultimos-30-dias", domingo)
    # As setas andam um do mesmo tamanho: a semana, o ano e os 12 meses (meses inteiros), os N.
    assert previous_period(date(2026, 11, 9), date(2026, 11, 15)) == (
        date(2026, 11, 2),
        date(2026, 11, 8),
    )
    assert previous_period(date(2025, 1, 1), date(2025, 12, 31)) == (
        date(2024, 1, 1),
        date(2024, 12, 31),
    )
    assert next_period(date(2025, 12, 1), date(2026, 11, 30)) == (
        date(2026, 12, 1),
        date(2027, 11, 30),
    )
    assert previous_period(date(2026, 10, 2), domingo) == (date(2026, 8, 18), date(2026, 10, 1))


def test_dias_do_periodo_ficam_entre_1_e_366() -> None:
    assert PeriodSpec(kind="ultimos-n-dias", days=366).days == 366
    for dias in (0, 367):
        with pytest.raises(ValidationError):
            PeriodSpec(kind="ultimos-n-dias", days=dias)


def _csv(conteudo: bytes, separador: str = ";") -> list[list[str]]:
    return list(csv.reader(io.StringIO(conteudo.decode("utf-8-sig")), delimiter=separador))


def test_csv_de_um_bloco() -> None:
    dados = _dados(
        [
            _tarefa(ANA, 90, INICIO, extra=60, cliente=FARMACIA),
            _tarefa(ANA, 30, INICIO, cliente=PADARIA),
            _tarefa(BIA, 15, INICIO),
        ],
        concluidos=[_chamado(INICIO, {ANA}, PADARIA)],
    )
    bloco = Block(visual="table", dimension="client", measures=["hours", "closed"], top=2)
    linhas = _csv(csv_export.render_block(dados, run(dados, bloco, INICIO, FIM), "pt-BR"))
    assert linhas == [
        ["Cliente", "Horas", "Horas (min)", "Chamados concluídos"],
        ["'=Farmácia", "1,50", "90", "0"],  # texto com cara de fórmula ganha o apóstrofo
        ["Padaria", "0,50", "30", "1"],
        ["Outros", "0,25", "15", "0"],
        ["Total", "2,25", "135", "1"],
    ]
    semanas = Block(visual="columns", dimension="month", measures=["overtime"])
    linhas = _csv(csv_export.render_block(dados, run(dados, semanas, INICIO, FIM), "en"), ",")
    assert linhas == [
        ["Month", "Overtime", "Overtime (min)"],
        ["2026-10", "1.00", "60"],
        ["Total", "1.00", "60"],
    ]
    lista = run(dados, Block(visual="tasks", only_overtime=True), INICIO, FIM)
    linhas = _csv(csv_export.render_block(dados, lista, "pt-BR"))
    assert linhas[0][:5] == ["Quando", "Pessoa", "Chamado", "Título", "Cliente"]
    assert linhas[1][:5] == ["01/10/2026 10:00", "Ana", "1000", "Impressora", "'=Farmácia"]
    assert linhas[1][5:] == ["1,50", "90", "1,00", "60"]


# --- medidas de chamados (fase 3) -------------------------------------------------------------

AGUARDANDO, CONCLUIDO = 2, 4
TIPOS = {PENDENTE: "open", AGUARDANDO: "waiting", CONCLUIDO: "closed"}


def _hora(h: float) -> datetime:
    return datetime(2026, 10, 5, tzinfo=TZ) + timedelta(hours=h)


def test_tempo_liquido() -> None:
    # Sem espera: o líquido é o bruto.
    assert net_minutes(_hora(0), _hora(10), [(_hora(10), PENDENTE, CONCLUIDO)], TIPOS) == 600
    # Duas idas a Aguardando (2 h e 1 h) saem do líquido.
    mudancas = [
        (_hora(1), PENDENTE, AGUARDANDO),
        (_hora(3), AGUARDANDO, PENDENTE),
        (_hora(5), PENDENTE, AGUARDANDO),
        (_hora(6), AGUARDANDO, PENDENTE),
        (_hora(10), PENDENTE, CONCLUIDO),
    ]
    assert net_minutes(_hora(0), _hora(10), mudancas, TIPOS) == 7 * 60
    # Reaberto: o tempo em que ficou concluído (das 4 às 8) não conta.
    reaberto = [
        (_hora(4), PENDENTE, CONCLUIDO),
        (_hora(8), CONCLUIDO, PENDENTE),
        (_hora(10), PENDENTE, CONCLUIDO),
    ]
    assert net_minutes(_hora(0), _hora(10), reaberto, TIPOS) == 6 * 60
    # Conclusão com data informada (às 6), registrada depois: o resto não conta.
    informada = [(_hora(2), PENDENTE, AGUARDANDO), (_hora(9), AGUARDANDO, CONCLUIDO)]
    assert net_minutes(_hora(0), _hora(6), informada, TIPOS) == 2 * 60


def test_medidas_de_chamados() -> None:
    concluidos = [
        _chamado(INICIO, {ANA}, numero=1, lead=60, net_lead=30),
        _chamado(INICIO, {ANA}, numero=2, lead=180, net_lead=180, reopened=True),
        _chamado(INICIO, {BIA}, numero=3, lead=600, net_lead=500),
    ]
    dados = _dados(
        [],
        concluidos=concluidos,
        cancelados=[_chamado(INICIO, {BIA}, numero=4)],
        em_aberto=[
            _chamado(FIM, {ANA}, numero=5, age=60),  # até 1 dia
            _chamado(FIM, {ANA}, numero=6, age=2 * 24 * 60),  # 1 a 3 dias
            _chamado(FIM, {BIA}, numero=7, age=30 * 24 * 60),  # mais de 7
        ],
    )
    medidas = ["closed", "canceled", "backlog", "lead_time", "net_lead_time", "reopen_rate"]
    cartoes = run(dados, Block(visual="cards", measures=medidas), INICIO, FIM)
    assert cartoes.total == {
        "closed": 3,
        "canceled": 1,
        "backlog": 3,
        "lead_time": 180,  # a mediana, não a média
        "net_lead_time": 180,
        "reopen_rate": 3333,  # 33,33%
    }
    por_pessoa = run(
        dados, Block(visual="table", dimension="person", measures=medidas), INICIO, FIM
    )
    assert [(r.label, r.values["lead_time"], r.values["reopen_rate"]) for r in por_pessoa.rows] == [
        ("Ana", 120, 5000),
        ("Bia", 600, 0),
    ]
    idades = run(dados, Block(visual="columns", dimension="age", measures=["backlog"]), INICIO, FIM)
    assert [(r.key, r.values["backlog"]) for r in idades.rows] == [(0, 1), (1, 1), (2, 0), (3, 1)]
    # Sem concluídos, a mediana e a porcentagem não têm base.
    vazio = run(
        _dados([]), Block(visual="cards", measures=["lead_time", "reopen_rate"]), INICIO, FIM
    )
    assert vazio.total == {"lead_time": None, "reopen_rate": None}


def test_periodo_anterior() -> None:
    assert previous_period(date(2026, 10, 1), date(2026, 10, 31)) == (
        date(2026, 9, 1),
        date(2026, 9, 30),
    )
    assert previous_period(date(2026, 1, 1), date(2026, 3, 31)) == (
        date(2025, 10, 1),
        date(2025, 12, 31),
    )
    # Ano até a data: as mesmas datas do ano anterior (29/02 vira 28/02), mesmo que sejam meses
    # inteiros; sem ser o ano até a data, os meses de antes.
    assert previous_period(date(2026, 1, 1), date(2026, 10, 24), year_to_date=True) == (
        date(2025, 1, 1),
        date(2025, 10, 24),
    )
    assert previous_period(date(2028, 1, 1), date(2028, 2, 29), year_to_date=True) == (
        date(2027, 1, 1),
        date(2027, 2, 28),
    )
    assert previous_period(date(2028, 1, 1), date(2028, 2, 29)) == (
        date(2027, 11, 1),
        date(2027, 12, 31),
    )
    # Os demais: o mesmo número de dias, logo antes.
    assert previous_period(date(2026, 10, 18), date(2026, 10, 24)) == (
        date(2026, 10, 11),
        date(2026, 10, 17),
    )


def test_mesmo_periodo_do_ano_anterior() -> None:
    # Meses inteiros: os mesmos meses, com o fevereiro de cada ano.
    assert year_before(date(2026, 10, 1), date(2026, 10, 31)) == (
        date(2025, 10, 1),
        date(2025, 10, 31),
    )
    assert year_before(date(2025, 2, 1), date(2025, 2, 28)) == (
        date(2024, 2, 1),
        date(2024, 2, 29),
    )
    assert year_before(date(2024, 2, 1), date(2024, 2, 29)) == (
        date(2023, 2, 1),
        date(2023, 2, 28),
    )
    assert year_before(date(2025, 12, 1), date(2026, 11, 30)) == (
        date(2024, 12, 1),
        date(2025, 11, 30),
    )
    # Semanas inteiras: 52 semanas antes, de segunda a domingo.
    assert year_before(date(2026, 10, 19), date(2026, 10, 25)) == (
        date(2025, 10, 20),
        date(2025, 10, 26),
    )
    assert date(2025, 10, 20).weekday() == 0
    # As demais: as mesmas datas; o 29 de fevereiro vira 28.
    assert year_before(date(2026, 1, 1), date(2026, 10, 24)) == (
        date(2025, 1, 1),
        date(2025, 10, 24),
    )
    assert year_before(date(2024, 2, 29), date(2024, 3, 10)) == (
        date(2023, 2, 28),
        date(2023, 3, 10),
    )
    # A escolha da comparação.
    outubro = (date(2026, 10, 1), date(2026, 10, 31))
    assert comparison_period(*outubro, "none") is None
    assert comparison_period(*outubro, "previous") == previous_period(*outubro)
    assert comparison_period(*outubro, "year") == year_before(*outubro)


def test_configuracao_da_versao_1_e_convertida() -> None:
    antiga = {"version": 1, "period": {"kind": "mes-atual", "compare": True}, "blocks": []}
    assert upgrade(antiga)["period"]["compare"] == "previous"
    assert upgrade(antiga)["version"] == 2
    sem = {"version": 1, "period": {"kind": "mes-atual", "compare": False}}
    assert upgrade(sem)["period"]["compare"] == "none"
    assert upgrade({"version": 1})["version"] == 2  # sem o campo, o padrão
    modelo = ReportModel(
        config={**antiga, "blocks": [{"visual": "cards", "measures": ["hours"]}]},
    )
    assert config_of(modelo).period.compare == "previous"
    assert upgrade({"version": 2, "period": {"compare": "year"}})["period"]["compare"] == "year"


def test_periodo_seguinte() -> None:
    # Simétrico ao anterior: os meses seguintes (o trimestre, o seguinte), as mesmas datas do ano
    # seguinte no ano até a data, os demais com o mesmo número de dias logo depois.
    assert next_period(date(2026, 9, 1), date(2026, 9, 30)) == (
        date(2026, 10, 1),
        date(2026, 10, 31),
    )
    assert next_period(date(2026, 1, 31), date(2026, 1, 31)) == (date(2026, 2, 1), date(2026, 2, 1))
    assert next_period(date(2025, 10, 1), date(2025, 12, 31)) == (
        date(2026, 1, 1),
        date(2026, 3, 31),
    )
    assert next_period(date(2025, 12, 1), date(2026, 1, 31)) == (
        date(2026, 2, 1),
        date(2026, 3, 31),
    )
    assert next_period(date(2025, 1, 1), date(2025, 10, 24), year_to_date=True) == (
        date(2026, 1, 1),
        date(2026, 10, 24),
    )
    assert next_period(date(2028, 1, 1), date(2028, 2, 29), year_to_date=True) == (
        date(2029, 1, 1),
        date(2029, 2, 28),
    )
    assert next_period(date(2026, 9, 27), date(2026, 10, 26)) == (
        date(2026, 10, 27),
        date(2026, 11, 25),
    )
    # Ida e volta.
    for inicio, fim in [
        (date(2026, 10, 1), date(2026, 10, 31)),
        (date(2026, 9, 27), date(2026, 10, 26)),
    ]:
        assert previous_period(*next_period(inicio, fim)) == (inicio, fim)


def test_csv_dos_chamados_e_da_porcentagem() -> None:
    concluido = _chamado(INICIO, {ANA}, PADARIA, numero=7, lead=90, net_lead=None, reopened=True)
    concluido.finished_at = concluido.created_at + timedelta(minutes=90)
    dados = _dados([], concluidos=[concluido])
    linhas = _csv(csv_export.render_tickets(dados, [concluido], "closed", "pt-BR"))
    assert linhas[0][-6:] == [
        "Concluído em",
        "Tempo até a conclusão",
        "Tempo até a conclusão (min)",
        "Tempo até a conclusão, líquido",
        "Tempo até a conclusão, líquido (min)",
        "Reaberto",
    ]
    assert linhas[1][:6] == ["7", "Impressora", "Padaria", "TI", "Pendente", "Ana"]
    assert linhas[1][6:] == ["01/10/2026 00:00", "01/10/2026 01:30", "1,50", "90", "", "", "Sim"]
    bloco = Block(visual="table", dimension="person", measures=["reopen_rate", "lead_time"])
    linhas = _csv(csv_export.render_block(dados, run(dados, bloco, INICIO, FIM), "pt-BR"))
    assert linhas[1] == ["Ana", "100,0", "1,50", "90"]
