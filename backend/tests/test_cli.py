import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from chamados import cli
from chamados.config import get_settings


@pytest.fixture(autouse=True)
def _banco_de_teste(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_openapi_em_arquivo(tmp_path: Path) -> None:
    out = tmp_path / "openapi.json"
    cli.main(["openapi", "-o", str(out)])
    spec = json.loads(out.read_text())
    assert spec["info"]["title"] == "TicketFlow"
    assert "/api/health" in spec["paths"]


def test_openapi_na_saida_padrao(capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(["openapi"])
    assert '"/api/health"' in capsys.readouterr().out


def test_db_upgrade_downgrade_current(capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(["db", "downgrade", "base"])
    cli.main(["db", "upgrade"])
    cli.main(["db", "current"])
