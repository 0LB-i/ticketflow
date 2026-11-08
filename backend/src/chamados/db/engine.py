"""Conexão com o PostgreSQL (SQLAlchemy 2 async + psycopg 3)."""

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_engine(database_url: str) -> AsyncEngine:
    # Sem JIT: o filtro de visibilidade (vários OR EXISTS) infla o custo estimado e o PostgreSQL
    # passava ~0,7 s compilando uma consulta que roda em 30 ms (ADR 0012).
    # Prazos: uma consulta travada (plano ruim, espera de trava) não segura para sempre uma
    # conexão do pool e as travas dela. 60 s é folga sobre a mais lenta medida (o relatório de
    # 12 meses, ~4,4 s sob carga). 5 min de transação parada porque o PDF dos relatórios é
    # gerado numa thread com a transação aberta (o de 148 páginas leva ~8 s, e o ZIP de Clientes
    # geral faz um por cliente); o prazo conta cada pausa separadamente. As migrações têm engine
    # própria (migrations/env.py), sem prazo.
    return create_async_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={
            "options": "-c jit=off -c statement_timeout=60s"
            " -c idle_in_transaction_session_timeout=5min"
        },
    )
