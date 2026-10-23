"""Catálogos de idioma das telas do servidor (web/locales/)."""

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import pytest

from chamados.web import i18n
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


def test_catalogo_conferido_no_maximo_uma_vez_por_segundo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """t() é chamado centenas de vezes por tela: a data do arquivo não é conferida a cada um,
    mas uma mudança no JSON continua valendo logo (o --reload só olha os .py)."""
    relogio = [1000.0]
    monkeypatch.setattr(i18n, "LOCALES_DIR", tmp_path)
    monkeypatch.setattr(i18n, "_catalogs", {})
    monkeypatch.setattr(time, "monotonic", lambda: relogio[0])
    arquivo = tmp_path / "xx.json"
    arquivo.write_text('{"a": "um"}')
    assert i18n.catalog("xx") == {"a": "um"}
    arquivo.write_text('{"a": "dois"}')
    os.utime(arquivo, (2_000_000_000, 2_000_000_000))
    relogio[0] += 0.5
    assert i18n.catalog("xx") == {"a": "um"}  # conferido há menos de 1 s
    relogio[0] += 1
    assert i18n.catalog("xx") == {"a": "dois"}
