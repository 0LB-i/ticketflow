"""Textos das telas do servidor, nos dois idiomas (pt-BR e en).

Os catálogos são os mesmos JSON da SPA (`frontend/src/i18n/`), para as duas interfaces não
divergirem enquanto convivem (ADR 0011). Na troca final eles passam para `web/locales/`.
"""

import json
import re
from functools import cache
from typing import Any

from chamados.config import REPO_ROOT
from chamados.core.i18n import DEFAULT_LOCALE

LOCALES_DIR = REPO_ROOT / "frontend" / "src" / "i18n"
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


@cache
def catalog(locale: str) -> dict[str, Any]:
    with (LOCALES_DIR / f"{locale}.json").open(encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    return data


def _lookup(messages: dict[str, Any], key: str) -> str | None:
    node: Any = messages
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, str) else None


def translate(locale: str, key: str, **values: object) -> str:
    """Texto da chave (`login.titulo`) com os marcadores (`{nome}`) preenchidos.

    Sem a chave no idioma, usa o português; sem ela em nenhum, mostra a própria chave, como a
    SPA, para a falta aparecer na tela em vez de quebrar a página.
    """
    text = _lookup(catalog(locale), key) or _lookup(catalog(DEFAULT_LOCALE), key) or key
    return _PLACEHOLDER.sub(lambda m: str(values.get(m.group(1), m.group(0))), text)
