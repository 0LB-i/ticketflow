"""Início do chamado (`started_at`), ajustável por quem registra.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tickets",
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    # Chamados que já existiam começaram quando foram registrados.
    op.execute("UPDATE tickets SET started_at = created_at")


def downgrade() -> None:
    op.drop_column("tickets", "started_at")
