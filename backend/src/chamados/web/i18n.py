"""Textos das telas do servidor, nos dois idiomas (pt-BR e en).

Os catálogos ficam em `web/locales/` (`pt-BR.json` e `en.json`), com as mesmas chaves e os
mesmos marcadores nos dois idiomas (tests/test_web_i18n.py).
"""

import json
import re
import time
from pathlib import Path
from typing import Any

from chamados.core.i18n import DEFAULT_LOCALE

LOCALES_DIR = Path(__file__).parent / "locales"
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


# Cada tela chama t() centenas de vezes: a data do arquivo é conferida no máximo uma vez por
# segundo, não a cada texto.
CHECK_EVERY = 1.0
# idioma → (data do arquivo, quando foi conferida, catálogo)
_catalogs: dict[str, tuple[float, float, dict[str, Any]]] = {}


def catalog(locale: str) -> dict[str, Any]:
    """O catálogo do idioma, lido de novo quando o arquivo muda (o --reload do uvicorn só olha
    os .py)."""
    now = time.monotonic()
    cached = _catalogs.get(locale)
    if cached is not None and now - cached[1] < CHECK_EVERY:
        return cached[2]
    path = LOCALES_DIR / f"{locale}.json"
    mtime = path.stat().st_mtime
    messages: dict[str, Any]
    if cached is None or cached[0] != mtime:
        with path.open(encoding="utf-8") as f:
            messages = json.load(f)
    else:
        messages = cached[2]
    _catalogs[locale] = (mtime, now, messages)
    return messages


def _lookup(messages: dict[str, Any], key: str) -> str | None:
    node: Any = messages
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, str) else None


def translate(locale: str, key: str, **values: object) -> str:
    """Texto da chave (`login.titulo`) com os marcadores (`{nome}`) preenchidos.

    Sem a chave no idioma, usa o português; sem ela em nenhum, mostra a própria chave, para a
    falta aparecer na tela em vez de quebrar a página.
    """
    text = _lookup(catalog(locale), key) or _lookup(catalog(DEFAULT_LOCALE), key) or key
    return _PLACEHOLDER.sub(lambda m: str(values.get(m.group(1), m.group(0))), text)
