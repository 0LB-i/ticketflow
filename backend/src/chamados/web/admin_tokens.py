"""Tokens de API (docs/05), só para quem administra os usuários: criar (no próprio nome), ver os
tokens ativos de todas as pessoas, com o filtro por pessoa, e revogar. O valor do token aparece uma
vez só, na própria resposta da criação (sem redirecionar: um aviso no cookie o guardaria no
navegador). Os dados vêm de `identity/admin_tokens.py`."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from chamados.core.permissions import P
from chamados.db.session import DB
from chamados.modules.identity import admin_tokens as api
from chamados.modules.identity.schemas import ApiTokenCreated, ApiTokenIn
from chamados.web.page import LoggedPage, check_csrf, requires, safe_next

router = APIRouter()

TokensAdmin = Annotated[LoggedPage, requires(P.ADMIN_USERS)]
Field = Annotated[str, Form()]
URL = "/admin/tokens"
DAYS = (30, 90, 365)


def _uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


async def _page(
    page: LoggedPage,
    db: DB,
    *,
    pessoa: str | None = None,
    created: ApiTokenCreated | None = None,
    form: dict[str, str] | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    everyone = (await api.list_api_tokens(page.auth, db)).items
    person = _uuid(pessoa)
    tokens = [t for t in everyone if t.user.id == person] if person else everyone
    people = {t.user.id: t.user.display_name for t in everyone}
    by_name = sorted(((str(i), n) for i, n in people.items()), key=lambda o: o[1].casefold())
    return page.render(
        "admin/tokens.html",
        status_code=status_code,
        tokens=tokens,
        person=str(person) if person in people else "",
        people_options=[("", page.t("tokensAdmin.todasAsPessoas")), *by_name],
        created=created,
        form=form or {"nome": "", "escopo": "read", "dias": "90"},
        error=error,
        days_options=[(str(d), page.t("tokens.dias", n=d)) for d in DAYS],
        now=datetime.now(UTC),
        base_url=page.request.app.state.settings.app_base_url.rstrip("/"),
    )


@router.get(URL)
async def tokens_page(page: TokensAdmin, db: DB, pessoa: str | None = None) -> HTMLResponse:
    return await _page(page, db, pessoa=pessoa)


@router.post(URL)
async def create_token(
    page: TokensAdmin,
    db: DB,
    request: Request,
    csrf_token: Field = "",
    nome: Field = "",
    escopo: Field = "read",
    dias: Field = "90",
) -> Response:
    check_csrf(page, csrf_token)
    form = {"nome": nome, "escopo": escopo, "dias": dias}
    if not nome.strip():
        return await _page(page, db, form=form, error=page.t("tokens.semNome"), status_code=422)
    try:
        data = ApiTokenIn.model_validate({"name": nome, "scope": escopo, "days": dias})
        created = await api.create_api_token(data, page.auth, db, request)
    except ValidationError:
        error = page.t("comum.erroInesperado")
    except HTTPException as exc:
        error = page.api_message(exc)
    else:
        return await _page(page, db, created=created, status_code=201)
    return await _page(page, db, form=form, error=error, status_code=422)


@router.post(URL + "/{token_id}/revogar")
async def revoke_token(
    token_id: str,
    page: TokensAdmin,
    db: DB,
    request: Request,
    csrf_token: Field = "",
    volta: Field = URL,
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
