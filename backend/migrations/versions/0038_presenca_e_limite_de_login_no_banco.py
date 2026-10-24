"""`ticket_presence` e `login_ip_failures` (UNLOGGED): a presença no chamado e o limite de login
por IP saem da memória da API, para valerem com vários workers.

Revision ID: 0038
Revises: 0037
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ticket_presence",
        sa.Column("ticket_id", postgresql.UUID(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.public_id"],
            name=op.f("ticket_presence_ticket_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("ticket_presence_user_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("ticket_id", "user_id", name=op.f("ticket_presence_pkey")),
        prefixes=["UNLOGGED"],
    )
    op.create_table(
        "login_ip_failures",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("ip", sa.Text(), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("login_ip_failures_pkey")),
        prefixes=["UNLOGGED"],
    )
    op.create_index("login_ip_failures_ip_idx", "login_ip_failures", ["ip", "at"])


def downgrade() -> None:
    op.drop_table("login_ip_failures")
    op.drop_table("ticket_presence")
