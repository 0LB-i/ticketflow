"""Data do cancelamento: `tickets.canceled_at`, como o `closed_at` dos concluídos.

Os já cancelados ficam com a última alteração, a melhor aproximação que havia.

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tickets", sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        """
        UPDATE tickets SET canceled_at = updated_at
        FROM ticket_statuses s
        WHERE s.id = tickets.status_id AND s.kind = 'canceled'
        """
    )


def downgrade() -> None:
    op.drop_column("tickets", "canceled_at")
