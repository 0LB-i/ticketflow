"""Respostas de erro no formato RFC 9457 (Problem Details), docs/05."""

from http import HTTPStatus
from typing import Any, cast

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.status import HTTP_422_UNPROCESSABLE_CONTENT, HTTP_500_INTERNAL_SERVER_ERROR

from chamados.core.i18n import DEFAULT_LOCALE, request_locale, translate

log = structlog.get_logger(__name__)

PROBLEM_JSON = "application/problem+json"

TITLES = {
    400: "Requisição inválida",
    401: "Não autenticado",
    403: "Acesso negado",
    404: "Não encontrado",
    405: "Método não permitido",
    409: "Conflito",
    422: "Dados inválidos",
    429: "Muitas requisições",
    500: "Erro interno",
    503: "Serviço indisponível",
}


def problem(
    status: int, detail: str | None = None, locale: str = DEFAULT_LOCALE, **extra: Any
) -> JSONResponse:
    """Erro no formato RFC 9457, com título e mensagem no idioma pedido (core/i18n.py)."""
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": translate(TITLES.get(status, "Erro"), locale),
        "status": status,
    }
    if detail:
        body["detail"] = translate(detail, locale)
    body.update(extra)
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON)


async def http_error(request: Request, error: Exception) -> JSONResponse:
    exc = cast(HTTPException, error)
    # Sem detalhe próprio, o Starlette repete a frase padrão em inglês ("Not Found"): omitir.
    default = HTTPStatus(exc.status_code).phrase
    detail = exc.detail if isinstance(exc.detail, str) and exc.detail != default else None
    response = problem(exc.status_code, detail, request_locale(request))
    if exc.headers:
        response.headers.update(exc.headers)
    return response


async def validation_error(request: Request, error: Exception) -> JSONResponse:
    exc = cast(RequestValidationError, error)
    errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    return problem(HTTP_422_UNPROCESSABLE_CONTENT, locale=request_locale(request), errors=errors)


async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    log.exception("erro_nao_tratado", path=request.url.path)
    return problem(HTTP_500_INTERNAL_SERVER_ERROR, locale=request_locale(request))


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, http_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(Exception, _unhandled_error)
