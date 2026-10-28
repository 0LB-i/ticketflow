"""As telas chamam as funções das rotas da API direto, e aí a dependência `require(P.X)` da rota
não roda (ARCHITECTURE 3.11). Estes testes garantem que toda tela que chama uma função protegida
confere a mesma permissão com `requires(P.X)`: uma tela nova sem ela falha aqui, em vez de abrir
a administração para qualquer pessoa logada.
"""

import ast
import inspect
from collections.abc import Callable
from types import ModuleType
from typing import Any

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from chamados.core.permissions import P
from chamados.modules.attachments import router as attachments
from chamados.modules.audit import router as audit
from chamados.modules.catalog import router as catalog
from chamados.modules.clients import router as clients
from chamados.modules.identity import admin_router, admin_tokens
from chamados.modules.identity import router as identity
from chamados.modules.organization import router as organization
from chamados.modules.reports import router as reports
from chamados.modules.system import router as system
from chamados.modules.tickets import router as tickets
from chamados.web import admin, auth, company, settings, ticket, tokens
from chamados.web import admin_tokens as web_admin_tokens
from chamados.web import board as web_board
from chamados.web import clients as web_clients
from chamados.web import reports as web_reports
from chamados.web import reports_downloads as web_reports_downloads
from chamados.web import tickets as web_tickets

API: tuple[ModuleType, ...] = (admin_router, admin_tokens, attachments, audit, catalog, clients)
API += (identity,)
API += (organization, reports, system, tickets)
WEB: tuple[ModuleType, ...] = (
    admin,
    auth,
    company,
    settings,
    ticket,
    tokens,
    web_clients,
    web_reports,
    web_reports_downloads,
)
WEB += (web_tickets, web_admin_tokens, web_board)

# Cada área da administração e o que as telas dela exigem.
AREAS = {
    "/admin/usuarios": {P.ADMIN_USERS},
    "/admin/tokens": {P.ADMIN_USERS},
    "/admin/grupos": {P.ADMIN_ORGANIZATION},
    "/admin/configuracoes": {P.ADMIN_SETTINGS},
    "/admin/empresa": {P.ADMIN_SETTINGS},
    "/admin/clientes": {P.CLIENT_VIEW, P.CLIENT_MANAGE},
}
# Quem tem a da esquerda também tem as da direita (Actor.permissions dá as duas de clientes).
IMPLIES: dict[P, set[P]] = {P.CLIENT_MANAGE: {P.CLIENT_VIEW}}


def _permissions(dependant: Dependant) -> set[P]:
    """As permissões que `require(P.X)` (API) ou `requires(P.X)` (telas) conferem, em toda a
    árvore de dependências: as duas guardam a permissão na closure."""
    found: set[P] = set()
    for dep in dependant.dependencies:
        for cell in getattr(dep.call, "__closure__", None) or ():
            if isinstance(cell.cell_contents, P):
                found.add(cell.cell_contents)
        found |= _permissions(dep)
    return found


def _routes(module: ModuleType) -> list[APIRoute]:
    return [r for r in module.router.routes if isinstance(r, APIRoute)]


def _protected() -> dict[Callable[..., Any], set[P]]:
    """Funções de rota da API que exigem uma permissão global."""
    return {
        r.endpoint: perms for m in API for r in _routes(m) if (perms := _permissions(r.dependant))
    }


class _Calls(ast.NodeVisitor):
    """Percorre uma função da tela: as permissões das funções protegidas da API que ela usa
    (chamadas, ou passadas adiante como em `api_call = tickets_api.add_watcher`) e as funções do
    mesmo módulo que ela chama. Dentro de `if page.can("x")`, a permissão x já foi conferida."""

    def __init__(self, module: ModuleType, protected: dict[Callable[..., Any], set[P]]) -> None:
        self.module, self.protected = module, protected
        self.guards: list[set[P]] = []
        self.required: set[P] = set()
        self.names: set[str] = set()

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        guard = {
            P(arg.value)
            for call in ast.walk(node.test)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "can"
            for arg in call.args
            if isinstance(arg, ast.Constant) and arg.value in set(P)
        }
        self.guards.append(guard)
        for stmt in node.body:
            self.visit(stmt)
        self.guards.pop()
        for stmt in node.orelse:
            self.visit(stmt)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.value, ast.Name):
            owner = getattr(self.module, node.value.id, None)
            fn = getattr(owner, node.attr, None) if isinstance(owner, ModuleType) else None
            if fn in self.protected:
                self.required |= self.protected[fn] - set().union(*self.guards)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        self.names.add(node.id)


def _calls(module: ModuleType, protected: dict[Callable[..., Any], set[P]]) -> dict[str, set[P]]:
    """Para cada função do módulo da tela: as permissões que ela precisa conferir, pelas funções
    protegidas que usa direto ou por outra função do mesmo módulo."""
    tree = ast.parse(inspect.getsource(module))
    functions = {
        f.name: f for f in tree.body if isinstance(f, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    direct: dict[str, set[P]] = {}
    local: dict[str, set[str]] = {}
    for name, f in functions.items():
        visitor = _Calls(module, protected)
        for stmt in f.body:
            visitor.visit(stmt)
        direct[name] = visitor.required
        local[name] = (visitor.names & functions.keys()) - {name}

    def needed(name: str, seen: frozenset[str] = frozenset()) -> set[P]:
        result = set(direct[name])
        for other in local[name] - seen:
            result |= needed(other, seen | {name})
        return result

    return {name: needed(name) for name in functions}


def _covered(required: set[P], granted: set[P]) -> bool:
    implied = granted.union(*(IMPLIES.get(p, set()) for p in granted))
    return required <= implied


def test_a_lista_de_modulos_esta_completa() -> None:
    """Um módulo novo de telas ou de API precisa entrar nas listas acima."""
    import pkgutil

    import chamados.web

    telas = {m.name for m in pkgutil.iter_modules(chamados.web.__path__)}
    com_rotas = {m for m in telas if hasattr(getattr(chamados.web, m, None), "router")}
    assert com_rotas == {m.__name__.rsplit(".", 1)[1] for m in WEB}


def test_telas_que_chamam_funcoes_protegidas_conferem_a_permissao() -> None:
    protected = _protected()
    assert protected  # as rotas de administração foram encontradas
    faltando = []
    for module in WEB:
        calls = _calls(module, protected)
        for route in _routes(module):
            required = calls.get(route.endpoint.__name__, set())
            if not _covered(required, _permissions(route.dependant)):
                faltando.append((route.path, sorted(required)))
    assert faltando == []


def test_telas_de_administracao_exigem_a_permissao_da_area() -> None:
    for module in WEB:
        for route in _routes(module):
            if not route.path.startswith("/admin/"):
                continue
            area = next((a for a in AREAS if route.path.startswith(a)), None)
            assert area is not None, f"{route.path}: área nova? Inclua em AREAS"
            granted = _permissions(route.dependant)
            assert granted and granted <= AREAS[area], route.path
            if area == "/admin/clientes" and "POST" in (route.methods or set()):
                assert P.CLIENT_MANAGE in granted, route.path


def test_o_teste_percebe_uma_tela_sem_requires() -> None:
    """Prova do próprio teste: tirar a permissão de uma tela que chama a API é percebido."""
    protected = _protected()
    calls = _calls(admin, protected)
    rota = next(r for r in _routes(admin) if r.path == "/admin/usuarios/{user_id}/excluir")
    assert P.ADMIN_USERS in calls[rota.endpoint.__name__]
    assert not _covered(calls[rota.endpoint.__name__], set())
