"""Matriz de permissões do docs/08 §8.3, tabelada (docs/12 §12.7)."""

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from chamados.core.permissions import ROLES, SUPERVISOR, Actor, P, can, effective_permissions

SUPERVISIONADO = 10
OUTRO_GRUPO = 20

agente = Actor(user_id=1, role="agent", teams=frozenset({SUPERVISIONADO, OUTRO_GRUPO}))
supervisor = Actor(
    user_id=2,
    role="agent",
    teams=frozenset({SUPERVISIONADO, OUTRO_GRUPO}),
    supervises=frozenset({SUPERVISIONADO}),
)
admin = Actor(user_id=3, role="admin")
admin_do_grupo = Actor(user_id=5, role="agent", manages_clients=True)
auditor = Actor(user_id=4, role="auditor")

S, N = True, False
# Permissão: (agente, supervisor no próprio grupo, admin, auditor) — docs/08, tabela de papéis.
MATRIZ = {
    P.TICKET_CREATE: (S, S, S, N),
    P.TICKET_VIEW_TEAM: (S, S, S, S),
    P.TICKET_VIEW_ALL: (N, N, S, S),
    P.TICKET_COMMENT: (S, S, S, N),
    P.TICKET_EDIT: (S, S, S, N),
    P.TICKET_ASSIGN_SELF: (S, S, S, N),
    P.TICKET_ASSIGN_OTHERS: (S, S, S, N),
    P.TICKET_TRANSFER: (S, S, S, N),
    P.TICKET_TRANSITION: (S, S, S, N),
    P.TICKET_APPROVE: (N, S, S, N),
    P.TICKET_WATCH: (S, S, S, N),
    P.TICKET_MERGE: (S, S, S, N),
    P.TICKET_BULK: (N, S, S, N),
    P.TICKET_HIDE_CONTENT: (N, S, S, N),
    P.TICKET_EXPORT: (N, S, S, S),
    P.KB_READ: (S, S, S, S),
    P.KB_WRITE: (S, S, S, N),
    P.KB_PUBLISH: (N, S, S, N),
    P.REPORT_VIEW_TEAM: (N, S, S, S),
    P.REPORT_VIEW_ALL: (N, N, S, S),
    P.ADMIN_USERS: (N, N, S, N),
    P.ADMIN_ORGANIZATION: (N, N, S, N),
    P.ADMIN_CATALOG: (N, N, S, N),
    P.ADMIN_SETTINGS: (N, N, S, N),
    P.AUDIT_VIEW: (N, N, S, S),
    P.CLIENT_VIEW: (N, N, N, N),  # só pelo grupo Administradores
    P.CLIENT_MANAGE: (N, N, N, N),
}


def test_matriz_cobre_o_catalogo_inteiro() -> None:
    assert set(MATRIZ) == set(P)


@pytest.mark.parametrize("permissao", list(MATRIZ))
def test_matriz(permissao: P) -> None:
    esperado = MATRIZ[permissao]
    obtido = tuple(
        can(ator, permissao, SUPERVISIONADO) for ator in (agente, supervisor, admin, auditor)
    )
    assert obtido == esperado


@pytest.mark.parametrize("permissao", sorted(SUPERVISOR))
def test_supervisao_nao_vale_em_outro_grupo(permissao: P) -> None:
    assert not can(supervisor, permissao, OUTRO_GRUPO)
    assert not can(supervisor, permissao)


def test_permissoes_efetivas_incluem_as_de_supervisor() -> None:
    assert "ticket.approve" not in effective_permissions(agente)
    assert "ticket.approve" in effective_permissions(supervisor)


def _migracao(numero: str) -> Any:
    caminho = next(Path(__file__).parents[2].glob(f"migrations/versions/{numero}_*.py"))
    spec = importlib.util.spec_from_file_location(f"migracao_{numero}", caminho)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_clientes_so_pelo_grupo_administradores() -> None:
    for permissao in ("client.view", "client.manage"):
        assert permissao in effective_permissions(admin_do_grupo)
        assert permissao not in effective_permissions(admin)


def test_papeis_da_migracao_batem_com_o_catalogo() -> None:
    # Papéis criados na 0002; permissões acrescentadas depois (0010: clientes; 0015: atribuir
    # a outro membro) e retiradas (0016: prioridade; 0027 e 0029: clientes, que passaram ao
    # grupo Administradores).
    novas = [_migracao(n).NEW_PERMISSIONS for n in ("0010", "0015")]
    retiradas = [_migracao(n).REMOVED_PERMISSIONS for n in ("0016", "0027", "0029")]
    papeis = _migracao("0002").SYSTEM_ROLES + _migracao("0045").SYSTEM_ROLES  # 0045: Cliente
    assert {codigo for codigo, _, _ in papeis} == set(ROLES)
    for codigo, _, permissoes in papeis:
        esperado = set(permissoes).union(*(n.get(codigo, []) for n in novas))
        esperado -= set().union(*(r.get(codigo, []) for r in retiradas))
        assert esperado == {str(p) for p in ROLES[codigo]}, codigo


def test_papel_cliente_nao_tem_nenhuma_permissao() -> None:
    cliente = Actor(user_id=9, role="client", client_id=1)
    assert effective_permissions(cliente) == []
    assert not any(can(cliente, p, SUPERVISIONADO) for p in P)
