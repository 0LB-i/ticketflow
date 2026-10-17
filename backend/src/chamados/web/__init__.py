"""Interface web renderizada no servidor: Jinja2 + HTMX + Tailwind (ADR 0011)."""

from fastapi import APIRouter

from chamados.web import auth

router = APIRouter(include_in_schema=False)
router.include_router(auth.router)
