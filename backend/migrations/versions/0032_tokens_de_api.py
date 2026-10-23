"""Tokens de API (`Authorization: Bearer`), em nome de um usuário.

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "public_id",
            postgresql.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("scope IN ('read', 'write')", name=op.f("api_tokens_scope_check")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("api_tokens_user_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("api_tokens_pkey")),
        sa.UniqueConstraint("public_id", name=op.f("api_tokens_public_id_key")),
        sa.UniqueConstraint("token_hash", name=op.f("api_tokens_token_hash_key")),
    )
    op.create_index(op.f("api_tokens_user_id_idx"), "api_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("api_tokens_user_id_idx"), table_name="api_tokens")
    op.drop_table("api_tokens")
