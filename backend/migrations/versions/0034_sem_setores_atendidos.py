"""Sem setores atendidos: sai a tabela `departments` e `tickets.department_id`.

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("tickets", "department_id")
    op.drop_table("departments")


def downgrade() -> None:
    """Volta a estrutura vazia: os setores apagados não voltam."""
    op.create_table(
        "departments",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "public_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["departments.id"], name=op.f("departments_parent_id_fkey")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("departments_pkey")),
        sa.UniqueConstraint("code", name=op.f("departments_code_key")),
        sa.UniqueConstraint(
            "parent_id",
            "name",
            name=op.f("departments_parent_id_name_key"),
            postgresql_nulls_not_distinct=True,
        ),
        sa.UniqueConstraint("public_id", name=op.f("departments_public_id_key")),
    )
    op.add_column("tickets", sa.Column("department_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        op.f("tickets_department_id_fkey"), "tickets", "departments", ["department_id"], ["id"]
    )
