"""Regras puras dos chamados, tabeladas: o que cada perfil pode fazer em cada situação
(docs/08 §8.5, docs/10 §10.5).
"""

import pytest

from chamados.core.permissions import Actor
from chamados.modules.tickets.rules import TicketState, allowed_actions

GRUPO, OUTRO = 10, 20
membro = Actor(user_id=1, role="agent", teams=frozenset({GRUPO}))
responsavel = Actor(user_id=2, role="agent", teams=frozenset({GRUPO}))
supervisor = Actor(user_id=3, role="agent", teams=frozenset({GRUPO}), supervises=frozenset({GRUPO}))
registrou = Actor(user_id=4, role="agent", teams=frozenset({GRUPO}))
observador_de_fora = Actor(user_id=5, role="agent", teams=frozenset({OUTRO}))
grupo_anterior = Actor(user_id=6, role="agent", teams=frozenset({OUTRO}))
supervisor_de_outro = Actor(
    user_id=9, role="agent", teams=frozenset({OUTRO}), supervises=frozenset({OUTRO})
)
admin = Actor(user_id=7, role="admin")
auditor = Actor(user_id=8, role="auditor")


def situacao(kind: str, *, ator: Actor, assignee: int | None = 2) -> TicketState:
    return TicketState(
        team_id=GRUPO,
        kind=kind,
        created_by_id=registrou.user_id,
        assignee_id=assignee,
        is_watcher=ator is observador_de_fora,
    )


DO_GRUPO = {
    "comment",
    "watch_self",
    "edit",
    "set_status",
    "set_status_closed",
    "manage_watchers",
    "transfer",
}
DONO = {"wait", "close", "cancel"}

# Chamado Pendente, com responsável (docs/08 §8.5)
PENDENTE = [
    (membro, DO_GRUPO | {"assign_self", "assign_others", "unassign"}),
    (responsavel, DO_GRUPO | DONO | {"assign_others", "unassign"}),
    (supervisor, DO_GRUPO | DONO | {"assign_self", "assign_others", "unassign", "bulk"}),
    (registrou, DO_GRUPO | {"assign_self", "assign_others", "unassign", "cancel"}),
    (observador_de_fora, {"comment", "watch_self"}),
    (grupo_anterior, {"watch_self"}),
    (supervisor_de_outro, {"watch_self"}),
    (admin, DO_GRUPO | DONO | {"assign_others", "unassign", "bulk"}),
    (auditor, set()),
]


@pytest.mark.parametrize(("ator", "esperado"), PENDENTE)
def test_acoes_no_chamado_pendente(ator: Actor, esperado: set[str]) -> None:
    assert allowed_actions(ator, situacao("open", ator=ator)) == esperado


def test_na_fila_ninguem_devolve() -> None:
    assert "unassign" not in allowed_actions(
        supervisor, situacao("open", ator=supervisor, assignee=None)
    )


# Transições permitidas por situação (docs/10 §10.5)
TRANSICOES = {"wait", "resume", "close", "reopen", "cancel"}
FLUXO = [
    ("waiting", membro, {"resume"}),
    ("waiting", responsavel, {"resume", "cancel"}),
    ("waiting", registrou, {"resume", "cancel"}),
    ("closed", membro, {"reopen"}),
    ("closed", supervisor, {"reopen"}),
    ("canceled", supervisor, set()),
    ("canceled", admin, set()),
]


@pytest.mark.parametrize(("kind", "ator", "esperado"), FLUXO)
def test_transicoes(kind: str, ator: Actor, esperado: set[str]) -> None:
    assert allowed_actions(ator, situacao(kind, ator=ator)) & TRANSICOES == esperado


@pytest.mark.parametrize("kind", ["closed", "canceled"])
def test_finalizado_nao_se_atribui_nem_transfere(kind: str) -> None:
    acoes = allowed_actions(supervisor, situacao(kind, ator=supervisor))
    assert not acoes & {"assign_self", "assign_others", "unassign", "transfer"}
    assert {"comment", "edit", "set_status"} <= acoes  # reabrir pelo formulário


# Em revisão ("Em espera de revisão"): só o supervisor do grupo ou o admin escolhe um status
# concluído (Entregue, Concluído); os demais continuam escolhendo os outros status.
EM_REVISAO = [
    (membro, False),
    (responsavel, False),
    (registrou, False),
    (supervisor, True),
    (admin, True),
]


@pytest.mark.parametrize(("ator", "conclui"), EM_REVISAO)
def test_em_revisao_so_o_supervisor_conclui(ator: Actor, conclui: bool) -> None:
    estado = TicketState(
        team_id=GRUPO,
        kind="waiting",
        created_by_id=registrou.user_id,
        assignee_id=responsavel.user_id,
        is_watcher=False,
        in_review=True,
    )
    acoes = allowed_actions(ator, estado)
    assert "set_status" in acoes
    assert ("set_status_closed" in acoes) is conclui
