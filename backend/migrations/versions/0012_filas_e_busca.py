"""Filas e busca: última visita a cada chamado (novidades) e busca textual em português.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TICKET_SEARCH = (
    "setweight(to_tsvector('pt_br'::regconfig, title), 'A') || "
    "setweight(to_tsvector('pt_br'::regconfig, description), 'B')"
)
COMMENT_SEARCH = "to_tsvector('pt_br'::regconfig, body)"


def upgrade() -> None:
    op.create_table(
        "ticket_reads",
        sa.Column("ticket_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "read_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            name=op.f("ticket_reads_ticket_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("ticket_reads_user_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("ticket_id", "user_id", name=op.f("ticket_reads_pkey")),
    )
    op.add_column(
        "tickets",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(TICKET_SEARCH, persisted=True),
            nullable=True,
        ),
    )
    op.create_index("tickets_search_idx", "tickets", ["search_vector"], postgresql_using="gin")
    op.add_column(
        "ticket_comments",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(COMMENT_SEARCH, persisted=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ticket_comments_search_idx",
        "ticket_comments",
        ["search_vector"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ticket_comments_search_idx", table_name="ticket_comments")
    op.drop_column("ticket_comments", "search_vector")
    op.drop_index("tickets_search_idx", table_name="tickets")
    op.drop_column("tickets", "search_vector")
    op.drop_table("ticket_reads")
