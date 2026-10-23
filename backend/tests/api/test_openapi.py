"""O comando `chamados openapi`: as rotas da API em JSON (docs/05)."""

import json
from pathlib import Path

import pytest

from chamados import cli

pytestmark = pytest.mark.usefixtures("cli_no_banco_de_teste")


def test_openapi_em_arquivo(tmp_path: Path) -> None:
    out = tmp_path / "openapi.json"
    cli.main(["openapi", "-o", str(out)])
    spec = json.loads(out.read_text())
    assert spec["info"]["title"] == "TicketFlow"
    assert "/api/health" in spec["paths"]


def test_openapi_na_saida_padrao(capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(["openapi"])
    assert '"/api/health"' in capsys.readouterr().out
