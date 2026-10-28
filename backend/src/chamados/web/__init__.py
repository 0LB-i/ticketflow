"""Interface web renderizada no servidor: Jinja2 + HTMX + Tailwind (ADR 0011)."""

from fastapi import APIRouter

from chamados.web import (
    admin,
    admin_tokens,
    auth,
    board,
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

router = APIRouter(include_in_schema=False)
router.include_router(auth.router)
router.include_router(tickets.router)
# Depois da lista: /chamados/novo antes do /chamados/{número}.
router.include_router(ticket.router)
router.include_router(board.router)
router.include_router(clients.router)
router.include_router(admin.router)
router.include_router(admin_tokens.router)
router.include_router(settings.router)
router.include_router(company.router)
router.include_router(reports.router)
router.include_router(reports_all_clients.router)
router.include_router(reports_downloads.router)
router.include_router(tokens.router)
