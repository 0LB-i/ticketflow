"""Interface web renderizada no servidor: Jinja2 + HTMX + Tailwind (ADR 0011)."""

from fastapi import APIRouter, Response

from chamados.web import (
    admin,
    admin_tokens,
    agenda,
    auth,
    board,
    client_panel,
    clients,
    company,
    reports,
    reports_all_clients,
    reports_downloads,
    settings,
    ticket,
    tickets,
    tokens,
)
from chamados.web.page import PREFETCH_RULES

router = APIRouter(include_in_schema=False)

# Regras do Chrome (Speculation Rules) para pedir a tela assim que o mouse encosta num link do menu
# (eager: ~10 ms no Chrome 141+), antes do clique. Só os links com data-pre-carrega: abrir um
# chamado grava a visita (mark_read), então a lista não entra. Só prefetch (sem prerender): os
# blocos dos relatórios não rodam à toa.
# Vão pelo cabeçalho Speculation-Rules (page.py), porque a CSP não aceita script embutido.
_PREFETCH_RULES = (
    '{"prefetch": [{"where": {"selector_matches": "a[data-pre-carrega]:not([aria-current])"},'
    ' "eagerness": "eager"}]}'
)


@router.get(PREFETCH_RULES)
def prefetch_rules() -> Response:
    return Response(
        _PREFETCH_RULES,
        media_type="application/speculationrules+json",
        headers={"Cache-Control": "public, max-age=3600"},
    )


router.include_router(auth.router)
router.include_router(tickets.router)
# Depois da lista: /chamados/novo antes do /chamados/{número}.
router.include_router(ticket.router)
router.include_router(board.router)
router.include_router(agenda.router)
router.include_router(clients.router)
router.include_router(admin.router)
router.include_router(admin_tokens.router)
router.include_router(settings.router)
router.include_router(company.router)
router.include_router(reports.router)
router.include_router(reports_all_clients.router)
router.include_router(reports_downloads.router)
router.include_router(tokens.router)
router.include_router(client_panel.router)
