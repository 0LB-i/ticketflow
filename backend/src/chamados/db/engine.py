"""Conexão com o PostgreSQL (SQLAlchemy 2 async + psycopg 3)."""

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_engine(database_url: str) -> AsyncEngine:
    # Sem JIT: o filtro de visibilidade (vários OR EXISTS) infla o custo estimado e o PostgreSQL
    # passava ~0,7 s compilando uma consulta que roda em 30 ms (ADR 0012).
    return create_async_engine(
        database_url, pool_pre_ping=True, connect_args={"options": "-c jit=off"}
    )
