"""Migrações sobem e descem (docs/12 §12.4) e a busca em português ignora acentos."""

from alembic import command
from sqlalchemy import create_engine, text

from chamados.cli import alembic_config


def _tsvector(url: str, texto: str) -> str:
    engine = create_engine(url)
    with engine.connect() as conn:
        value = conn.execute(text("SELECT to_tsvector('pt_br', :t)::text"), {"t": texto})
        result = str(value.scalar_one())
    engine.dispose()
    return result


def test_busca_pt_br_sem_acentos(database_url: str) -> None:
    assert _tsvector(database_url, "Impressão") == _tsvector(database_url, "impressao")


def test_downgrade_e_upgrade(database_url: str) -> None:
    cfg = alembic_config(database_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    assert "impress" in _tsvector(database_url, "Impressora")
