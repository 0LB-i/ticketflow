"""Migrações sobem e descem (docs/12 §12.4), os comandos `chamados db` e a busca em português
ignora acentos."""

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.orm import Session

from chamados import cli
from chamados.cli import alembic_config
from chamados.modules.identity.models import User
from chamados.modules.identity.passwords import verify_password
from chamados.modules.organization.models import Team


def _tsvector(url: str, texto: str) -> str:
    engine = create_engine(url)
    with engine.connect() as conn:
        value = conn.execute(text("SELECT to_tsvector('pt_br', :t)::text"), {"t": texto})
        result = str(value.scalar_one())
    engine.dispose()
    return result


def test_busca_pt_br_sem_acentos(database_url: str) -> None:
    assert _tsvector(database_url, "Impressão") == _tsvector(database_url, "impressao")


@pytest.mark.usefixtures("migracoes")
def test_downgrade_e_upgrade(database_url: str, db: Session) -> None:
    # O `db` começa com as tabelas vazias: o que o teste anterior deixou (ex.: chamado sem
    # categoria) impediria o downgrade.
    cfg = alembic_config(database_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    assert "impress" in _tsvector(database_url, "Impressora")


@pytest.mark.usefixtures("migracoes", "cli_no_banco_de_teste")
def test_db_upgrade_downgrade_current(sync_engine: Engine, db: Session) -> None:
    # Só a última migração: descer até a base e voltar é o test_downgrade_e_upgrade.
    def revisao() -> str:
        with sync_engine.connect() as conn:
            return str(conn.scalar(text("SELECT version_num FROM alembic_version")))

    head = revisao()
    cli.main(["db", "downgrade", "-1"])
    assert revisao() != head
    cli.main(["db", "upgrade"])
    assert revisao() == head
    cli.main(["db", "current"])


@pytest.mark.usefixtures("migracoes")
def test_migracao_cria_o_admin_padrao(db: Session, database_url: str) -> None:
    """Administrador padrão admin/admin com troca obrigatória de senha (docs/09 §9.2)."""
    cfg = alembic_config(database_url)
    command.downgrade(cfg, "0002")
    command.upgrade(cfg, "head")
    admin = db.scalar(select(User).where(User.username == "admin"))
    assert admin is not None
    assert admin.email is None and admin.role.code == "admin"
    assert admin.must_change_password
    assert verify_password(admin.password_hash, "admin")[0]
    assert [(m.team.name, m.role) for m in admin.memberships] == [("Administradores", "member")]
    # Rodar de novo não duplica nem recria quem já existe. Encerra a transação antes:
    # ela segura um lock em users e a migração ficaria esperando para sempre.
    db.rollback()
    command.downgrade(cfg, "0002")
    command.upgrade(cfg, "head")
    assert len(db.scalars(select(User).where(User.username == "admin")).all()) == 1
    assert len(db.scalars(select(Team).where(Team.name == "Administradores")).all()) == 1
