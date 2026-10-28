"""`report_exports`: os PDFs da aba Clientes baixados com um cliente só, para o Histórico e a
cascata de Relatórios (docs/14 §14.7).

Revision ID: 0042
Revises: 0041
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "report_exports",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("query", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('simple', 'detailed')", name=op.f("report_exports_kind_check")
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["clients.id"], name=op.f("report_exports_client_id_fkey")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("report_exports_user_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("report_exports_pkey")),
    )
    op.create_index(
        "report_exports_user_id_created_at_idx", "report_exports", ["user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("report_exports")
