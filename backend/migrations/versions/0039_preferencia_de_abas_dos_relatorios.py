"""`report_preferences`: a ordem e as abas escondidas de Relatórios, uma linha por pessoa
(docs/14 §14.8.1).

Revision ID: 0039
Revises: 0038
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "report_preferences",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("tabs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("report_preferences_user_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("report_preferences_pkey")),
    )


def downgrade() -> None:
    op.drop_table("report_preferences")
