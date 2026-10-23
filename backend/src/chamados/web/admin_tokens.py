"""Administração dos tokens de API (docs/05): os tokens ativos de todas as pessoas, com o filtro
por pessoa, e a revogação. Os dados vêm de `identity/admin_tokens.py`; criar fica com cada pessoa
(`/meus-tokens`)."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from chamados.core.permissions import P
from chamados.db.session import DB
from chamados.modules.identity import admin_tokens as api
from chamados.web.page import LoggedPage, check_csrf, requires, safe_next

router = APIRouter()

TokensAdmin = Annotated[LoggedPage, requires(P.ADMIN_USERS)]
URL = "/admin/tokens"


def _uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


@router.get(URL)
async def tokens_page(page: TokensAdmin, db: DB, pessoa: str | None = None) -> HTMLResponse:
    everyone = (await api.list_api_tokens(page.auth, db)).items
    person = _uuid(pessoa)
    tokens = [t for t in everyone if t.user.id == person] if person else everyone
    people = {t.user.id: t.user.display_name for t in everyone}
    by_name = sorted(((str(i), n) for i, n in people.items()), key=lambda o: o[1].casefold())
    return page.render(
        "admin/tokens.html",
        tokens=tokens,
        person=str(person) if person in people else "",
        people_options=[("", page.t("tokensAdmin.todasAsPessoas")), *by_name],
        now=datetime.now(UTC),
    )


@router.post(URL + "/{token_id}/revogar")
async def revoke_token(
    token_id: str,
    page: TokensAdmin,
    db: DB,
    request: Request,
    csrf_token: Annotated[str, Form()] = "",
    volta: Annotated[str, Form()] = URL,
) -> Response:
    check_csrf(page, csrf_token)
    back = safe_next(volta) if volta.startswith(URL) else URL
    response = RedirectResponse(back, status_code=303)
    try:
        await api.revoke_any_api_token(uuid.UUID(token_id), page.auth, db, request)
    except ValueError:
        page.flash(response, ("error", page.t("comum.erroInesperado")))
    except HTTPException as exc:
        page.flash(response, ("error", page.api_message(exc)))
    else:
        page.flash(response, ("success", page.t("tokens.revogado")))
    return response
