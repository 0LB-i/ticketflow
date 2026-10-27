"""O expediente de (pessoa, dia): precedência, vigências, feriados e os dias em texto
(docs/14 §14.7)."""

from datetime import date, datetime, time, timedelta

import pytest

from chamados.core.timezone import LOCAL_TZ
from chamados.modules.reports.builder import workdays
from chamados.modules.reports.service import outside_minutes
from chamados.modules.system.work_hours import (
    Calendar,
    Schedule,
    Source,
    describe,
    weekday_ranges,
    work_window,
)

DIAS = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")


@pytest.mark.parametrize(
    ("dias", "texto"),
    [
        ([0, 1, 2, 3, 4], "seg–sex"),
        ([0, 2, 4], "seg, qua, sex"),
        ([0, 1, 2, 5], "seg–qua, sáb"),
        ([0, 1], "seg, ter"),
        ([5, 6, 0, 1, 2, 3, 4], "seg–dom"),
        ([], ""),
    ],
)
def test_dias_em_faixas(dias: list[int], texto: str) -> None:
    assert weekday_ranges(dias, DIAS) == texto


def test_expediente_em_texto() -> None:
    assert describe(Schedule((0, 1, 2, 3, 4), time(8), time(18)), DIAS) == "seg–sex 08:00–18:00"


# --- o expediente de (pessoa, dia) ----------------------------------------------------------


def em(dia: date, hora: int) -> datetime:
    return datetime.combine(dia, time(hora), LOCAL_TZ)


SEGUNDA = date(2026, 10, 5)
TERCA = SEGUNDA + timedelta(days=1)
INSTALACAO = Schedule((0, 1, 2, 3, 4), time(8), time(18))
SUPORTE = Schedule((0, 1, 2, 3, 4, 5), time(10), time(19))
PLANTAO = Schedule((0, 1, 2, 3, 4, 5, 6), time(0), time(8))
ANA, BIA, CAIO, DANI = 1, 2, 3, 4
TIME_SUPORTE, TIME_REDE = 10, 20


def _calendario() -> Calendar:
    """A instalação; o Suporte com expediente; a Rede com expediente só a partir de terça; a Ana
    no Suporte; a Bia no Suporte com um próprio a partir de terça; o Caio no Suporte e na Rede;
    a Dani em nenhum grupo."""
    return Calendar(
        installation=[(date.min, INSTALACAO)],
        users={BIA: [(TERCA, PLANTAO)]},
        teams={TIME_SUPORTE: [(date.min, SUPORTE)], TIME_REDE: [(TERCA, PLANTAO)]},
        member_of={ANA: (TIME_SUPORTE,), BIA: (TIME_SUPORTE,), CAIO: (TIME_SUPORTE, TIME_REDE)},
        holidays=frozenset({SEGUNDA + timedelta(days=3)}),
    )


def test_precedencia_pessoa_grupo_instalacao() -> None:
    cal = _calendario()
    assert cal.source(DANI, SEGUNDA) == Source(INSTALACAO, "installation")
    assert cal.source(ANA, SEGUNDA) == Source(SUPORTE, "team", TIME_SUPORTE)
    assert cal.source(BIA, SEGUNDA) == Source(SUPORTE, "team", TIME_SUPORTE)
    assert cal.source(BIA, TERCA) == Source(PLANTAO, "own")
    assert cal.source(None, TERCA) == Source(INSTALACAO, "installation")


def test_pessoa_em_dois_grupos_com_expediente_segue_a_instalacao() -> None:
    cal = _calendario()
    # Na segunda, só o Suporte tem expediente; na terça, a Rede também.
    assert cal.source(CAIO, SEGUNDA) == Source(SUPORTE, "team", TIME_SUPORTE)
    assert cal.source(CAIO, TERCA) == Source(
        INSTALACAO, "installation", conflict=(TIME_SUPORTE, TIME_REDE)
    )


def test_vigencia_sem_expediente_proprio_volta_ao_de_cima() -> None:
    cal = _calendario()
    cal.users[BIA].append((TERCA + timedelta(days=1), None))
    cal.installation.append((TERCA + timedelta(days=1), PLANTAO))
    quarta = TERCA + timedelta(days=1)
    assert cal.source(BIA, quarta) == Source(SUPORTE, "team", TIME_SUPORTE)
    assert cal.source(DANI, quarta) == Source(PLANTAO, "installation")
    assert cal.source(DANI, TERCA) == Source(INSTALACAO, "installation")  # antes da mudança


def test_janela_e_feriado() -> None:
    cal = _calendario()
    quinta = SEGUNDA + timedelta(days=3)
    assert cal.window(ANA, SEGUNDA) == work_window(SEGUNDA, time(10), time(19))
    assert cal.window(ANA, quinta) is None  # feriado vale para todos
    assert cal.window(DANI, SEGUNDA + timedelta(days=5)) is None  # sábado
    assert cal.window(ANA, SEGUNDA + timedelta(days=5)) is not None  # o Suporte trabalha
    assert workdays(SEGUNDA, SEGUNDA + timedelta(days=6), cal, ANA) == 5
    assert workdays(SEGUNDA, SEGUNDA + timedelta(days=6), cal) == 4


@pytest.mark.parametrize(
    ("quem", "fim", "minutos", "fora"),
    [
        (DANI, em(SEGUNDA, 10), 60, 0),
        (ANA, em(SEGUNDA, 11), 90, 30),  # 09:30–11:00; o Suporte começa às 10:00
        (ANA, em(SEGUNDA, 19), 90, 0),
        # 22:00 de segunda à 01:00 de terça: na segunda (Suporte, até 19:00) tudo fora; na
        # terça, o próprio da Bia (00:00–08:00) cobre a 01:00 que passa da meia-noite.
        (BIA, em(TERCA, 1), 180, 120),
        (DANI, em(TERCA, 1), 180, 180),
    ],
)
def test_hora_extra_pelo_expediente_de_quem_fez(
    quem: int, fim: datetime, minutos: int, fora: int
) -> None:
    assert outside_minutes(fim, minutos, _calendario(), quem) == fora
