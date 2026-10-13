"""Anexos (docs/11): envios em duas etapas, vinculados ao chamado ou a um comentário.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "attachments",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "public_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("ticket_id", sa.BigInteger(), nullable=True),
        sa.Column("comment_id", sa.BigInteger(), nullable=True),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("uploaded_by", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("size_bytes > 0", name=op.f("attachments_size_bytes_check")),
        sa.CheckConstraint(
            "comment_id IS NULL OR ticket_id IS NOT NULL",
            name=op.f("attachments_comment_needs_ticket_check"),
        ),
        sa.CheckConstraint(
            "(linked_at IS NULL) = (ticket_id IS NULL)", name=op.f("attachments_linked_check")
        ),
        sa.ForeignKeyConstraint(
            ["comment_id"],
            ["ticket_comments.id"],
            name=op.f("attachments_comment_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            name=op.f("attachments_ticket_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"], ["users.id"], name=op.f("attachments_uploaded_by_fkey")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("attachments_pkey")),
        sa.UniqueConstraint("public_id", name=op.f("attachments_public_id_key")),
        sa.UniqueConstraint("storage_key", name=op.f("attachments_storage_key_key")),
    )
    op.create_index(
        "attachments_ticket_idx",
        "attachments",
        ["ticket_id"],
        postgresql_where=sa.text("ticket_id IS NOT NULL"),
    )
    op.create_index(
        "attachments_orphans_idx",
        "attachments",
        ["created_at"],
        postgresql_where=sa.text("linked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("attachments_orphans_idx", table_name="attachments")
    op.drop_index("attachments_ticket_idx", table_name="attachments")
    op.drop_table("attachments")
