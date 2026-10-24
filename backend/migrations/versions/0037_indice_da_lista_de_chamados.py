"""Índice `tickets_created_idx` (`created_at`, `id`): a ordem da lista de chamados e do cursor.

Sem ele, cada página da lista ordenava todos os chamados (benchmark, ARCHITECTURE.md §7.1).

Revision ID: 0037
Revises: 0036
Create Date: 2026-10-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("tickets_created_idx", "tickets", ["created_at", "id"])


def downgrade() -> None:
    op.drop_index("tickets_created_idx", table_name="tickets")
