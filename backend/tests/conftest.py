"""Testes de integração usam um PostgreSQL real (docs/12 §12.7).

TEST_DATABASE_URL escolhe o banco; o scripts/check.sh aponta para o 17 e, no modo completo,
também para o 16.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from fastapi.testclient import TestClient

from chamados.cli import alembic_config
from chamados.config import Settings
from chamados.main import create_app

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://chamados:chamados@localhost:5432/chamados_test"
)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """Banco de teste limpo e migrado até a última revisão."""
    cfg = alembic_config(TEST_DATABASE_URL)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield TEST_DATABASE_URL


@pytest.fixture
def settings(database_url: str, tmp_path: Path) -> Settings:
    return Settings(database_url=database_url, log_format="console", frontend_dist=tmp_path)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as c:
        yield c
