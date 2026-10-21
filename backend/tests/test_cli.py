import asyncio
import json
import os
import signal
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from chamados import cli
from chamados.config import Settings, get_settings
from chamados.modules.jobs import worker
from chamados.modules.jobs.models import Job


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


def test_db_upgrade_downgrade_current(
    capsys: pytest.CaptureFixture[str], sync_engine: Engine, db: Session
) -> None:
    # O `db` começa com as tabelas vazias: o que o teste anterior deixou impediria o downgrade.
    cli.main(["db", "downgrade", "base"])
    cli.main(["db", "upgrade"])
    # As extensões foram recriadas com novos OIDs: conexões antigas do pool guardam os velhos.
    sync_engine.dispose()
    cli.main(["db", "current"])


def test_worker_encerra_com_sigterm_depois_da_tarefa(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    db.add(Job(task="teste.sigterm"))
    db.commit()

    async def sigterm(_db: AsyncSession, _s: Settings, _args: dict[str, Any]) -> None:
        os.kill(os.getpid(), signal.SIGTERM)  # o que o systemctl stop faz
        await asyncio.sleep(0.1)

    monkeypatch.setitem(worker.TASKS, "teste.sigterm", sigterm)
    monkeypatch.setattr(worker, "ROUTINES", {})
    cli.main(["worker"])
    db.expire_all()
    assert db.scalars(select(Job.status)).one() == "done"
