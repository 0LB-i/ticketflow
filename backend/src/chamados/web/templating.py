"""Ambiente Jinja2 das telas do servidor."""

import os
from pathlib import Path

from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import Response
from starlette.types import Scope

from chamados.modules.attachments.files import TYPES
from chamados.web.markdown import render_markdown

WEB_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEB_DIR / "static"

templates = Jinja2Templates(directory=WEB_DIR / "templates")


def static(path: str) -> str:
    """Endereço de um arquivo de static/ com a data de modificação, para o navegador buscar de
    novo quando ele muda (CachedStaticFiles). Em nanossegundos: o app.css gerado duas vezes no
    mesmo segundo ganha outro endereço."""
    try:
        version = (STATIC_DIR / path).stat().st_mtime_ns
    except OSError:
        version = 0
    return f"/static/{path}?v={version}"


class CachedStaticFiles(StaticFiles):
    """Pasta static/. Pedido com ?v= (o endereço de static()) fica um ano no navegador, sem ele
    perguntar de novo a cada tela: um arquivo novo tem outro endereço. Sem ?v= (as fontes, que o
    CSS cita), vale o cache comum, pelo ETag."""

    def file_response(
        self,
        full_path: str | os.PathLike[str],
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        if scope["query_string"].startswith(b"v="):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


templates.env.globals["static"] = static
templates.env.filters["markdown"] = render_markdown
# Extensões aceitas pela API (docs/11 §11.2), para o seletor de arquivos já filtrar.
templates.env.globals["ACCEPTED_FILES"] = ",".join(f".{ext}" for ext in TYPES)
