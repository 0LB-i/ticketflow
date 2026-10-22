"""Índice das tarefas pela data em que foram feitas: os relatórios filtram o período por ela.

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ticket_comments_done_idx",
        "ticket_comments",
        ["done_at"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ticket_comments_done_idx", table_name="ticket_comments")
