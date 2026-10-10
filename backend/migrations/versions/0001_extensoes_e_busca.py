"""Extensões e configuração de busca textual em português (docs/04, esboco-schema.sql).

Revision ID: 0001
Revises:
Create Date: 2026-10-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Extensões "trusted": o dono do banco cria sem superusuário (docs/18 §18.3, passo 3).
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    # Português + remoção de acentos. Com regconfig explícito, to_tsvector é IMMUTABLE
    # e pode ser usado em colunas geradas.
    op.execute("CREATE TEXT SEARCH CONFIGURATION pt_br (COPY = portuguese)")
    op.execute(
        "ALTER TEXT SEARCH CONFIGURATION pt_br "
        "ALTER MAPPING FOR hword, hword_part, word WITH unaccent, portuguese_stem"
    )


def downgrade() -> None:
    op.execute("DROP TEXT SEARCH CONFIGURATION IF EXISTS pt_br")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
    op.execute("DROP EXTENSION IF EXISTS unaccent")
    op.execute("DROP EXTENSION IF EXISTS citext")
