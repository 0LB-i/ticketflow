"""Categoria do chamado deixa de ser obrigatória.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("tickets", "category_id", nullable=True)


def downgrade() -> None:
    # Falha se houver chamado sem categoria: escolha uma para eles antes de descer.
    op.alter_column("tickets", "category_id", nullable=False)
