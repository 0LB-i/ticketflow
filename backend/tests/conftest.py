"""Testes de integração usam um PostgreSQL real (docs/12 §12.7).

TEST_DATABASE_URL escolhe o banco; o scripts/check.sh aponta para o 17 e, no modo completo,
também para o 16.
"""

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from alembic import command
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.orm import Session

from chamados.cli import alembic_config
from chamados.config import Settings
from chamados.main import create_app
from chamados.modules.catalog.models import Category
from chamados.modules.identity import passwords
from chamados.modules.identity.models import User
from chamados.modules.identity.passwords import hash_password
from chamados.modules.organization.models import Role, Team, TeamMember

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://chamados:chamados@localhost:5432/chamados_test"
)
SENHA = "uma senha longa de teste"
TABELAS = (
    "ticket_events, ticket_comments, ticket_watchers, ticket_teams, tickets, categories, "
    "settings, audit_log, auth_tokens, user_sessions, team_members, teams, departments, users, "
    "clients"
)


@pytest.fixture(scope="session", autouse=True)
def _argon2_rapido() -> None:
    """Argon2 barato só nos testes; em produção valem os parâmetros padrão (lentos de propósito)."""
    passwords._hasher = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    passwords._DUMMY = passwords._hasher.hash("referencia")


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """Banco de teste limpo e migrado até a última revisão."""
    cfg = alembic_config(TEST_DATABASE_URL)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield TEST_DATABASE_URL


@pytest.fixture(scope="session")
def sync_engine(database_url: str) -> Iterator[Engine]:
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db(sync_engine: Engine) -> Iterator[Session]:
    """Sessão síncrona para preparar e conferir dados. Começa com o banco vazio (menos papéis)."""
    with sync_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABELAS} RESTART IDENTITY CASCADE"))
    with Session(sync_engine, expire_on_commit=False) as session:
        yield session


@dataclass
class FakeMailer:
    configured: bool = False
    sent: list[tuple[str, str, str]] = field(default_factory=list)

    def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))

    def last_link(self) -> str:
        match = re.search(r"https?://\S+", self.sent[-1][2])
        assert match
        return match.group(0)


@pytest.fixture
def settings(database_url: str, tmp_path: Path) -> Settings:
    return Settings(
        database_url=database_url,
        log_format="console",
        frontend_dist=tmp_path,
        cookie_secure=False,
        app_base_url="http://teste",
    )


@pytest.fixture
def mailer() -> FakeMailer:
    return FakeMailer()


@pytest.fixture
def client(settings: Settings, mailer: FakeMailer, db: Session) -> Iterator[TestClient]:
    app = create_app(settings)
    app.state.mailer = mailer
    with TestClient(app) as c:
        yield c


def criar_usuario(
    db: Session,
    email: str | None = "ana@exemplo.com",
    role: str = "agent",
    *,
    nome: str = "Ana Souza",
    senha: str | None = SENHA,
    ativo: bool = True,
    grupos: dict[str, str] | None = None,
    username: str | None = None,
    trocar_senha: bool = False,
) -> User:
    """Cria um usuário (e os grupos citados, se não existirem): grupos={"TI": "supervisor"}."""
    papel = db.scalar(select(Role).where(Role.code == role))
    user = User(
        email=email,
        full_name=nome,
        role=papel,
        password_hash=hash_password(senha) if senha else None,
        is_active=ativo,
        username=username,
        must_change_password=trocar_senha,
    )
    db.add(user)
    db.flush()
    for nome_grupo, papel_grupo in (grupos or {}).items():
        team = db.scalar(select(Team).where(Team.name == nome_grupo)) or Team(name=nome_grupo)
        db.add(team)
        db.flush()
        db.add(TeamMember(team_id=team.id, user_id=user.id, role=papel_grupo))
    db.commit()
    return user


def entrar(client: TestClient, email: str = "ana@exemplo.com", senha: str = SENHA) -> None:
    """Faz login e prepara o header CSRF para as próximas requisições."""
    r = client.post("/api/v1/auth/login", json={"login": email, "password": senha})
    assert r.status_code == 204, r.text
    client.headers["X-CSRF-Token"] = client.cookies["tf_csrf"]


def grupo(db: Session, nome: str) -> Team:
    """Grupo pelo nome, criado se ainda não existir."""
    team = db.scalar(select(Team).where(Team.name == nome))
    if team is None:
        team = Team(name=nome)
        db.add(team)
        db.commit()
    return team


def criar_categoria(
    db: Session,
    nome: str = "Impressão",
    *,
    grupo_padrao: str | None = None,
    confidencial: bool = False,
    tipo: str = "incident",
) -> Category:
    category = Category(
        name=nome,
        default_team_id=grupo(db, grupo_padrao).id if grupo_padrao else None,
        default_type=tipo,
        is_confidential=confidencial,
    )
    db.add(category)
    db.commit()
    return category
