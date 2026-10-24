"""Testes de integração usam um PostgreSQL real (docs/12 §12.7).

TEST_DATABASE_URL escolhe o banco; o scripts/check.sh aponta para o 17 e, no modo completo,
também para o 16.

O app (e o servidor MCP, que só de importar leva ~1 s) e o Alembic são importados dentro das
fixtures: os testes de regras puras (tests/unidade) não pagam por eles.
"""

import hashlib
import os
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from argon2 import PasswordHasher
from sqlalchemy import Engine, create_engine, event, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from chamados.config import Settings, get_settings
from chamados.modules.catalog.models import Category
from chamados.modules.clients.models import Client
from chamados.modules.identity import passwords
from chamados.modules.identity.models import User
from chamados.modules.identity.passwords import hash_password
from chamados.modules.organization.models import Role, Team, TeamMember

if TYPE_CHECKING:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://chamados:chamados@localhost:5432/chamados_test"
)
SENHA = "uma senha longa de teste"
MIGRACOES = Path(__file__).parents[1] / "migrations"
# Vêm das migrações e ficam de um teste para o outro.
FICAM = {"alembic_version", "roles", "ticket_statuses", "resolution_codes"}


@pytest.fixture(scope="session", autouse=True)
def _argon2_rapido() -> None:
    """Argon2 barato só nos testes; em produção valem os parâmetros padrão (lentos de propósito)."""
    passwords._hasher = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    passwords._DUMMY = passwords._hasher.hash("referencia")


def _tabelas() -> list[str]:
    """As tabelas que cada teste começa vazias, das filhas para as mães (a ordem das FKs)."""
    import chamados.db.models  # noqa: F401  (registra todos os modelos)
    from chamados.db.base import Base

    return [t.name for t in reversed(Base.metadata.sorted_tables) if t.name not in FICAM]


def _assinatura_das_migracoes() -> str:
    h = hashlib.sha256()
    for arquivo in sorted(MIGRACOES.rglob("*.py")):
        h.update(arquivo.read_bytes())
    return h.hexdigest()


# O conteúdo dos status: os testes os mudam (Configurações) e a limpeza os devolve.
STATUS = "SELECT md5(string_agg(s::text, ',' ORDER BY s.id)) FROM ticket_statuses s"


@pytest.fixture(scope="session")
def database_url() -> str:
    """Banco de teste migrado até a última revisão.

    Desce até a base e sobe de novo só quando algum arquivo de migrations/ mudou desde a última
    sessão, ou quando os status não estão como a migração os criou (a marca fica no comentário
    da tabela alembic_version): quem mexe nas telas não roda as migrações a cada vez. A ida e
    volta delas também é um teste (tests/banco).
    """
    from alembic import command
    from alembic.script import ScriptDirectory

    from chamados.cli import alembic_config

    cfg = alembic_config(TEST_DATABASE_URL)
    head = ScriptDirectory.from_config(cfg).get_current_head()
    assinatura = _assinatura_das_migracoes()
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as conn:
        marca = None
        if conn.scalar(text("SELECT to_regclass('alembic_version')")):
            marca = conn.execute(
                text(
                    "SELECT version_num, obj_description('alembic_version'::regclass) "
                    "FROM alembic_version"
                )
            ).first()
        em_dia = (
            marca is not None
            and marca[0] == head
            and marca[1] == f"{assinatura} {conn.scalar(text(STATUS))}"
        )
        if not em_dia:
            # O que o último teste deixou (ex.: chamado sem categoria) pode impedir o downgrade:
            # a migração 0006 volta a exigir a categoria. Só as tabelas que existem: num banco
            # novo ou numa revisão anterior, algumas ainda não foram criadas.
            existentes = [t for t in _tabelas() if conn.scalar(text(f"SELECT to_regclass('{t}')"))]
            if existentes:
                conn.execute(text(f"TRUNCATE {', '.join(existentes)} RESTART IDENTITY CASCADE"))
    if not em_dia:
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
        with engine.begin() as conn:
            marca_nova = f"{assinatura} {conn.scalar(text(STATUS))}"
            conn.exec_driver_sql(f"COMMENT ON TABLE alembic_version IS '{marca_nova}'")
    engine.dispose()
    return TEST_DATABASE_URL


@pytest.fixture(scope="session")
def sync_engine(database_url: str) -> Iterator[Engine]:
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def _limpeza(sync_engine: Engine) -> Iterator[Callable[[Connection], None]]:
    """Esvazia as tabelas antes de cada teste e devolve os status ao que a migração criou.

    DELETE, e não TRUNCATE: com tabelas quase vazias, o TRUNCATE de todas custava ~50 ms por
    teste, e o DELETE ~10 ms. O histórico só aceita inserção (um gatilho barra o DELETE), então
    ele vai por TRUNCATE. As sequências voltam ao início (o primeiro chamado é o 1000).
    """
    tabelas = _tabelas()
    with sync_engine.connect() as conn:
        status = [dict(s) for s in conn.execute(text("SELECT * FROM ticket_statuses")).mappings()]
        no_banco = conn.scalars(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        ).all()
        # Uma tabela sem modelo importado em db/models.py ficaria com o que o teste anterior
        # deixou.
        assert set(no_banco) - FICAM == set(tabelas), "tabela nova fora de chamados.db.models?"
        inicios = conn.execute(
            text(
                "SELECT s.seqrelid::regclass::text, s.seqstart FROM pg_sequence s "
                "JOIN pg_depend d ON d.objid = s.seqrelid AND d.deptype IN ('a', 'i') "
                "JOIN pg_class t ON t.oid = d.refobjid WHERE t.relname = ANY(:tabelas)"
            ),
            {"tabelas": tabelas},
        ).all()
    # O SQL só leva nomes de tabelas, colunas e sequências do próprio banco (S608).
    deletes = "".join(f"DELETE FROM {t};" for t in tabelas if t != "ticket_events")  # noqa: S608
    apagar = f"TRUNCATE ticket_events;{deletes}DELETE FROM ticket_statuses;"  # noqa: S608
    # Um teste que cria, renomeia ou remove status (as Configurações) não muda os do próximo.
    recriar_status = text(
        f"INSERT INTO ticket_statuses ({', '.join(status[0])}) OVERRIDING SYSTEM VALUE "  # noqa: S608
        f"VALUES ({', '.join(f':{c}' for c in status[0])})"
    )
    setvals = [f"setval('{nome}', {inicio}, false)" for nome, inicio in inicios]
    setvals.append("setval('ticket_statuses_id_seq', (SELECT max(id) FROM ticket_statuses))")
    sequencias = f"SELECT {', '.join(setvals)};"

    def limpar(conn: Connection) -> None:
        conn.exec_driver_sql(apagar)
        conn.execute(recriar_status, status)
        conn.exec_driver_sql(sequencias)

    yield limpar
    # No fim, os status voltam ao original: a próxima sessão não precisa refazer o banco.
    with sync_engine.begin() as conn:
        limpar(conn)


@pytest.fixture
def db(sync_engine: Engine, _limpeza: Callable[[Connection], None]) -> Iterator[Session]:
    """Sessão síncrona para preparar e conferir dados. Começa com o banco vazio (menos papéis)."""
    with sync_engine.begin() as conn:
        _limpeza(conn)
    with Session(sync_engine, expire_on_commit=False) as session:
        yield session


@dataclass
class FakeMailer:
    configured: bool = False
    sent: list[tuple[str, str, str]] = field(default_factory=list)

    def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))

    deliver = send

    def last_link(self) -> str:
        match = re.search(r"https?://\S+", self.sent[-1][2])
        assert match
        return match.group(0)


@pytest.fixture
def settings(database_url: str, tmp_path: Path) -> Settings:
    return Settings(
        database_url=database_url,
        log_format="console",
        cookie_secure=False,
        app_base_url="http://teste",
        files_dir=tmp_path / "files",
    )


@pytest.fixture
def mailer() -> FakeMailer:
    return FakeMailer()


@pytest.fixture(scope="session")
def app(database_url: str) -> "FastAPI":
    """Uma aplicação para a sessão toda: montá-la custa ~0,4 s (o FastAPI analisa cada rota)."""
    from chamados.main import create_app

    return create_app(Settings(database_url=database_url, log_format="console"))


@pytest.fixture(scope="session")
def _no_ar(app: "FastAPI") -> Iterator["TestClient"]:
    """O lifespan do app (a engine e o servidor MCP) sobe uma vez para a sessão toda: a cada
    teste, custava ~50 ms."""
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


def outra_sessao(client: "TestClient") -> "TestClient":
    """Mais um navegador no mesmo app: cookies e headers à parte, no event loop do lifespan."""
    from fastapi.testclient import TestClient

    outro = TestClient(client.app)
    outro.portal = client.portal
    return outro


@pytest.fixture
def client(
    app: "FastAPI", _no_ar: "TestClient", settings: Settings, mailer: FakeMailer, db: Session
) -> "TestClient":
    # O estado que as rotas leem de app.state começa do zero em cada teste.
    app.state.settings = settings
    app.state.mailer = mailer
    return outra_sessao(_no_ar)


@pytest.fixture
def migracoes(database_url: str, sync_engine: Engine, _no_ar: "TestClient") -> Iterator[None]:
    """Para os testes que descem e sobem as migrações: as extensões voltam com outros OIDs, que
    as conexões já abertas guardam. Depois do teste, os pools recomeçam do zero."""
    yield
    sync_engine.dispose()
    engine: AsyncEngine = _no_ar.app.state.engine  # type: ignore[attr-defined]
    assert _no_ar.portal is not None
    _no_ar.portal.call(engine.dispose)


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
        display_name=nome,
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


def entrar(client: "TestClient", email: str = "ana@exemplo.com", senha: str = SENHA) -> None:
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


def criar_cliente(db: Session, nome: str | None, documento: str, *, ativo: bool = True) -> str:
    """Cria uma empresa (com endereço) e devolve o id público."""
    cliente = Client(
        kind="company",
        name=nome,
        document=documento,
        postal_code="01310100",
        street="Avenida Paulista",
        number="1000",
        district="Bela Vista",
        city="São Paulo",
        state="SP",
        is_active=ativo,
    )
    db.add(cliente)
    db.commit()
    return str(cliente.public_id)


@pytest.fixture
def cenario(client: "TestClient", db: Session) -> dict[str, str]:
    """Ana e Bia (supervisora) no TI, Caio na Infra e um auditor; a Ana já entrou. Os ids
    públicos das pessoas, dos grupos, das categorias e do cliente padrão."""
    pessoas = {
        "ana": criar_usuario(db, "ana@x.com", nome="Ana", grupos={"TI": "member"}),
        "bia": criar_usuario(db, "bia@x.com", nome="Bia", grupos={"TI": "supervisor"}),
        "caio": criar_usuario(db, "caio@x.com", nome="Caio", grupos={"Infra": "member"}),
        "auditor": criar_usuario(db, "auditor@x.com", "auditor", nome="Auditor"),
    }
    entrar(client, "ana@x.com")
    return {
        **{nome: str(u.public_id) for nome, u in pessoas.items()},
        "ti": str(grupo(db, "TI").public_id),
        "infra": str(grupo(db, "Infra").public_id),
        "impressao": str(criar_categoria(db, "Impressão", grupo_padrao="TI").public_id),
        "sem_grupo": str(criar_categoria(db, "Diversos", tipo="task").public_id),
        "cliente": criar_cliente(db, "Cliente Padrão", "33445566000186"),
    }


@pytest.fixture
def cli_no_banco_de_teste(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """O comando `chamados` (cli.main) lê as configurações do ambiente: as do banco de teste."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("APP_BASE_URL", "http://teste")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@contextmanager
def consultas(client: "TestClient") -> Iterator[list[str]]:
    """O SQL que a aplicação executa dentro do bloco (para os testes de desempenho)."""
    feitas: list[str] = []

    def guardar(_conn: Connection, _cursor: object, statement: str, *_: object) -> None:
        feitas.append(statement)

    engine = client.app.state.engine.sync_engine  # type: ignore[attr-defined]
    event.listen(engine, "before_cursor_execute", guardar)
    try:
        yield feitas
    finally:
        event.remove(engine, "before_cursor_execute", guardar)
