"""Configurações da instalação (idioma, cores, logotipo) e idioma de cada usuário.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name=op.f("settings_updated_by_fkey")
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("settings_pkey")),
    )
    op.add_column("users", sa.Column("locale", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "locale")
    op.drop_table("settings")
