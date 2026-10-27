"""O expediente de (pessoa, dia): precedência, vigências, feriados e os dias em texto
(docs/14 §14.7)."""

from datetime import time

import pytest

from chamados.modules.system.work_hours import Schedule, describe, weekday_ranges

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
