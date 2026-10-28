"""Sai `report_models` (os modelos de relatório pessoais) e `report_preferences` (a ordem e as
abas escondidas de Relatórios): os relatórios ficam só com as abas prontas (docs/14 §14.8). O
downgrade recria as tabelas vazias; os modelos apagados não voltam.

Revision ID: 0044
Revises: 0043
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("report_preferences")
    op.drop_table("report_models")


def downgrade() -> None:
    op.create_table(
        "report_models",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "public_id",
            postgresql.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("report_models_owner_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("report_models_pkey")),
        sa.UniqueConstraint("public_id", name=op.f("report_models_public_id_key")),
    )
    op.create_index(
        "report_models_owner_id_name_key",
        "report_models",
        ["owner_id", sa.text("lower(name)")],
        unique=True,
    )
    op.create_index(
        "report_models_owner_id_default_key",
        "report_models",
        ["owner_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
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
