"""Tarefas (comentários): data em que foram feitas (`done_at`) e remoção (`deleted_at`).

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ticket_comments",
        sa.Column(
            "done_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    )
    # As tarefas que já existem foram feitas quando foram registradas.
    op.execute("UPDATE ticket_comments SET done_at = created_at")
    op.add_column("ticket_comments", sa.Column("deleted_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    # As removidas voltariam a aparecer: saem de vez, com os anexos (ON DELETE CASCADE).
    op.execute("DELETE FROM ticket_comments WHERE deleted_at IS NOT NULL")
    op.drop_column("ticket_comments", "deleted_at")
    op.drop_column("ticket_comments", "done_at")
