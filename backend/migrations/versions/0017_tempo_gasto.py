"""Tempo gasto em cada andamento (comentário) do chamado.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ticket_comments", sa.Column("time_spent_minutes", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f("ticket_comments_time_spent_minutes_check"),
        "ticket_comments",
        "time_spent_minutes > 0",
    )


def downgrade() -> None:
    op.drop_column("ticket_comments", "time_spent_minutes")  # leva junto o CHECK
