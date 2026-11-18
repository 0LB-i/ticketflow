"""Tokens de API (docs/05), só para quem administra os usuários: criar (no próprio nome, com as
permissões por área), ver os tokens ativos de todas as pessoas, com o filtro por pessoa, mudar as
permissões (`/admin/tokens/{id}`) e revogar. O valor do token aparece uma
vez só, na própria resposta da criação (sem redirecionar: um aviso no cookie o guardaria no
navegador). Os dados vêm de `identity/admin_tokens.py`."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from chamados.core.permissions import P
from chamados.db.session import DB
from chamados.modules.identity import admin_tokens as api
from chamados.modules.identity.schemas import ApiTokenCreated, ApiTokenIn, ApiTokenPermissionsIn
from chamados.modules.identity.token_access import ACTIONS, AREAS
from chamados.web.page import LoggedPage, check_csrf, requires, safe_next

router = APIRouter()

TokensAdmin = Annotated[LoggedPage, requires(P.ADMIN_USERS)]
Field = Annotated[str, Form()]
Checks = Annotated[list[str] | None, Form()]
URL = "/admin/tokens"
DAYS = (30, 90, 365)
NO_EXPIRY = "sem"  # a opção Sem validade do campo dias


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
    form: dict[str, Any] | None = None,
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
        form=form or {"nome": "", "permissoes": ["tickets.view"], "dias": "90"},
        areas=AREAS,
        actions=ACTIONS,
        error=error,
        days_options=[
            *((str(d), page.t("tokens.dias", n=d)) for d in DAYS),
            (NO_EXPIRY, page.t("tokens.semValidade")),
        ],
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
    permissoes: Checks = None,
    dias: Field = "90",
) -> Response:
    check_csrf(page, csrf_token)
    permissoes = permissoes or []
    form = {"nome": nome, "permissoes": permissoes, "dias": dias}
    if not nome.strip():
        return await _page(page, db, form=form, error=page.t("tokens.semNome"), status_code=422)
    if not permissoes:
        error = page.t("tokens.semPermissao")
        return await _page(page, db, form=form, error=error, status_code=422)
    try:
        days = None if dias == NO_EXPIRY else dias
        data = ApiTokenIn.model_validate({"name": nome, "permissions": permissoes, "days": days})
        created = await api.create_api_token(data, page.auth, db, request)
    except ValidationError:
        error = page.t("comum.erroInesperado")
    except HTTPException as exc:
        error = page.api_message(exc)
    else:
        return await _page(page, db, created=created, status_code=201)
    return await _page(page, db, form=form, error=error, status_code=422)


async def _edit_page(
    page: LoggedPage,
    db: DB,
    token_id: str,
    *,
    selected: list[str] | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    wanted = _uuid(token_id)
    token = next(
        (t for t in (await api.list_api_tokens(page.auth, db)).items if t.id == wanted), None
    )
    if token is None:
        raise HTTPException(404)
    return page.render(
        "admin/token_edit.html",
        status_code=status_code,
        token=token,
        selected=token.permissions if selected is None else selected,
        error=error,
        areas=AREAS,
        actions=ACTIONS,
    )


@router.get(URL + "/{token_id}")
async def edit_page(token_id: str, page: TokensAdmin, db: DB) -> HTMLResponse:
    return await _edit_page(page, db, token_id)


@router.post(URL + "/{token_id}")
async def save_permissions(
    token_id: str,
    page: TokensAdmin,
    db: DB,
    request: Request,
    csrf_token: Field = "",
    permissoes: Checks = None,
) -> Response:
    check_csrf(page, csrf_token)
    permissoes = permissoes or []
    if not permissoes:
        error = page.t("tokens.semPermissao")
        return await _edit_page(page, db, token_id, selected=[], error=error, status_code=422)
    try:
        data = ApiTokenPermissionsIn.model_validate({"permissions": permissoes})
        token = uuid.UUID(token_id)
    except (ValidationError, ValueError):
        error = page.t("comum.erroInesperado")
        return await _edit_page(
            page, db, token_id, selected=permissoes, error=error, status_code=422
        )
    response = RedirectResponse(URL, status_code=303)
    try:
        await api.update_api_token(token, data, page.auth, db, request)
    except HTTPException as exc:
        page.flash(response, ("error", page.api_message(exc)))
    else:
        page.flash(response, ("success", page.t("tokens.salvo")))
    return response


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
