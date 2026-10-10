"""Ambiente do Alembic. Roda com o driver síncrono do psycopg 3 (mesma URL da aplicação)."""

from alembic import context
from sqlalchemy import create_engine, pool

from chamados.db import models  # noqa: F401  (registra os modelos no metadata)
from chamados.db.base import Base

config = context.config
url = config.get_main_option("sqlalchemy.url")
if not url:
    raise RuntimeError("sqlalchemy.url não configurada (use o comando `chamados db`)")

target_metadata = Base.metadata

if context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
