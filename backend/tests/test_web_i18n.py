"""Catálogos de idioma das telas do servidor (web/locales/)."""

import json
import re
from typing import Any

from chamados.web.i18n import LOCALES_DIR, translate


def _flatten(obj: dict[str, Any], prefix: str = "") -> dict[str, list[str]]:
    """Chave → marcadores ({nome}) de cada mensagem."""
    out: dict[str, list[str]] = {}
    for key, value in obj.items():
        if isinstance(value, dict):
            out |= _flatten(value, f"{prefix}{key}.")
        else:
            out[f"{prefix}{key}"] = sorted(re.findall(r"\{(\w+)\}", str(value)))
    return out


def _load(locale: str) -> dict[str, Any]:
    result: dict[str, Any] = json.loads((LOCALES_DIR / f"{locale}.json").read_text("utf-8"))
    return result


def test_ingles_tem_as_mesmas_mensagens_e_marcadores() -> None:
    assert _flatten(_load("en")) == _flatten(_load("pt-BR"))


def test_traducao_com_marcadores_e_sem_a_chave() -> None:
    assert translate("en", "chamados.novo") == "New ticket"
    assert translate("pt-BR", "chamados.novo") == "Novo chamado"
    assert translate("pt-BR", "novoChamado.registrado", numero=1234) == "Chamado #1234 registrado"
    # Sem a chave em nenhum idioma, aparece a própria chave (a falta fica visível na tela).
    assert translate("en", "nao.existe") == "nao.existe"
