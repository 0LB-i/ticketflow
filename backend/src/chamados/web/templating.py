"""Ambiente Jinja2 das telas do servidor."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

WEB_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEB_DIR / "static"

templates = Jinja2Templates(directory=WEB_DIR / "templates")


def static(path: str) -> str:
    """Endereço de um arquivo de static/ com a data de modificação, para o navegador buscar de
    novo quando ele muda (a pasta é servida sem cache longo)."""
    try:
        version = int((STATIC_DIR / path).stat().st_mtime)
    except OSError:
        version = 0
    return f"/static/{path}?v={version}"


templates.env.globals["static"] = static
