"""Construtor guiado dos relatórios (docs/14 §14.8): o cálculo de cada bloco a partir dos dados do
período, as combinações recusadas, os períodos relativos e o CSV de um bloco. Sem banco: os
dados (`service.Facts`) são montados à mão.
"""

import csv
import io
from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException

from chamados.modules.catalog.models import TicketStatus
from chamados.modules.clients.models import Client
from chamados.modules.identity.models import User
from chamados.modules.organization.models import Team
from chamados.modules.reports import csv_export
from chamados.modules.reports.builder import (
    BUILTINS,
    OTHERS,
    Block,
    check_block,
    relative_period,
    run,
)
from chamados.modules.reports.service import TZ, Facts, TaskFact, TicketFact
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


def _chamado(dia: date, pessoas: set[int], cliente: int | None = None) -> TicketFact:
    return TicketFact(client_id=cliente, team_id=TI, status_id=PENDENTE, day=dia, people=pessoas)


def _dados(
    tarefas: list[TaskFact],
    registrados: list[TicketFact] | None = None,
    concluidos: list[TicketFact] | None = None,
) -> Facts:
    return Facts(
        work_hours=DEFAULT,
        tasks=tarefas,
        opened=registrados or [],
        closed=concluidos or [],
        users={ANA: User(id=ANA, display_name="Ana"), BIA: User(id=BIA, display_name="Bia")},
        clients={
            PADARIA: Client(id=PADARIA, name="Padaria"),
            MERCADO: Client(id=MERCADO, name="Mercado"),
            FARMACIA: Client(id=FARMACIA, name="=Farmácia"),
        },
        teams={TI: Team(id=TI, name="TI")},
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


def test_os_maiores_outros_e_ordem() -> None:
    dados = _dados(
        [
            _tarefa(ANA, 10, INICIO, cliente=PADARIA),
            _tarefa(ANA, 30, INICIO, cliente=MERCADO),
            _tarefa(ANA, 20, INICIO, cliente=FARMACIA),
            _tarefa(ANA, 5, INICIO),  # sem cliente
        ]
    )

    def linhas(**opcoes: object) -> list[tuple[object, int]]:
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
            "As barras agrupam por pessoa, cliente, grupo ou status.",
        ),
    ],
)
def test_combinacoes_recusadas(bloco: Block, erro: str) -> None:
    with pytest.raises(HTTPException) as exc:
        check_block(bloco)
    assert exc.value.status_code == 422 and exc.value.detail == erro


def test_modelos_prontos_sao_validos() -> None:
    for config in BUILTINS.values():
        for bloco in config.blocks:
            check_block(bloco)


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
