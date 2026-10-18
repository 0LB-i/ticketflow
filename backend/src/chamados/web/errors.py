"""Erros fora da API: uma página no visual do sistema, não o JSON (RFC 9457) da API.

Ex.: token CSRF de uma aba antiga, endereço com parâmetro inválido, envio de outro site.
"""

from http import HTTPStatus
from typing import cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import Response

from chamados.core import errors as api_errors
from chamados.core.i18n import translate
from chamados.web.page import get_page


def _is_api(request: Request) -> bool:
    return request.url.path.startswith(("/api/", "/static/"))


async def _error_page(request: Request, status: int, detail: str | None) -> Response:
    # A mesma montagem das telas: o idioma da pessoa, se houver sessão, ou o do sistema.
    async with request.app.state.sessionmaker() as db:
        page = await get_page(request, db, request.app.state.settings)
    return page.render(
        "error.html",
        status_code=status,
        title=translate(api_errors.TITLES.get(status, "Erro"), page.locale),
        detail=translate(detail, page.locale) if detail else page.t("comum.erroInesperado"),
    )


async def http_error(request: Request, error: Exception) -> Response:
    if _is_api(request):
        return await api_errors.http_error(request, error)
    exc = cast(HTTPException, error)
    # Sem detalhe próprio, o Starlette repete a frase padrão em inglês ("Not Found").
    default = HTTPStatus(exc.status_code).phrase
    detail = exc.detail if isinstance(exc.detail, str) and exc.detail != default else None
    response = await _error_page(request, exc.status_code, detail)
    if exc.headers:
        response.headers.update(exc.headers)
    return response


async def validation_error(request: Request, error: Exception) -> Response:
    if _is_api(request):
        return await api_errors.validation_error(request, error)
    return await _error_page(request, 422, None)


def register_web_error_handlers(app: FastAPI) -> None:
    """Por cima dos da API (core/errors.py), que continuam valendo em /api."""
    app.add_exception_handler(HTTPException, http_error)
    app.add_exception_handler(RequestValidationError, validation_error)
