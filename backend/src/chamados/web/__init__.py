"""Interface web renderizada no servidor: Jinja2 + HTMX + Tailwind (ADR 0011)."""

from fastapi import APIRouter

from chamados.web import auth, clients, ticket, tickets

router = APIRouter(include_in_schema=False)
router.include_router(auth.router)
router.include_router(tickets.router)
# Depois da lista: /chamados/novo antes do /chamados/{número}.
router.include_router(ticket.router)
router.include_router(clients.router)
