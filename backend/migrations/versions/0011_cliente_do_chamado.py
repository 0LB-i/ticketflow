"""Cliente atendido no chamado (`tickets.client_id`), opcional.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tickets", sa.Column("client_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        op.f("tickets_client_id_fkey"), "tickets", "clients", ["client_id"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint(op.f("tickets_client_id_fkey"), "tickets", type_="foreignkey")
    op.drop_column("tickets", "client_id")
