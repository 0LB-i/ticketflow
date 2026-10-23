"""Meus tokens de API (docs/05): a pessoa cria, vê e revoga os próprios. O valor do token aparece
uma vez só, na própria resposta da criação (sem redirecionar: um aviso no cookie o guardaria no
navegador). Os dados vêm das rotas `/me/tokens` da API.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from chamados.db.session import DB
from chamados.modules.identity import router as identity_api
from chamados.modules.identity.schemas import ApiTokenCreated, ApiTokenIn
from chamados.web.page import LoggedPage, LoggedPageDep, check_csrf

router = APIRouter()

Field = Annotated[str, Form()]
URL = "/meus-tokens"
DAYS = (30, 90, 365)


async def _page(
    page: LoggedPage,
    db: DB,
    *,
    created: ApiTokenCreated | None = None,
    form: dict[str, str] | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    tokens = (await identity_api.list_my_tokens(page.auth, db)).items
    return page.render(
        "tokens/index.html",
        status_code=status_code,
        tokens=tokens,
        created=created,
        form=form or {"nome": "", "escopo": "read", "dias": "90"},
        error=error,
        days_options=[(str(d), page.t("tokens.dias", n=d)) for d in DAYS],
        now=datetime.now(UTC),
        base_url=page.request.app.state.settings.app_base_url.rstrip("/"),
    )


@router.get(URL)
async def tokens_page(page: LoggedPageDep, db: DB) -> HTMLResponse:
    return await _page(page, db)


@router.post(URL)
async def create_token(
    page: LoggedPageDep,
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
        created = await identity_api.create_my_token(data, page.auth, db, request)
    except ValidationError:
        error = page.t("comum.erroInesperado")
    except HTTPException as exc:
        error = page.api_message(exc)
    else:
        return await _page(page, db, created=created, status_code=201)
    return await _page(page, db, form=form, error=error, status_code=422)


@router.post(URL + "/{token_id}/revogar")
async def revoke_token(
    token_id: str, page: LoggedPageDep, db: DB, request: Request, csrf_token: Field = ""
) -> Response:
    check_csrf(page, csrf_token)
    response = RedirectResponse(URL, status_code=303)
    try:
        await identity_api.revoke_my_token(uuid.UUID(token_id), page.auth, db, request)
    except ValueError:
        page.flash(response, ("error", page.t("comum.erroInesperado")))
    except HTTPException as exc:
        page.flash(response, ("error", page.api_message(exc)))
    else:
        page.flash(response, ("success", page.t("tokens.revogado")))
    return response
