"""Outbox de eventos e fila de tarefas (F1-S4-03), consumidos pelo `chamados worker`.

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outbox",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("outbox_pkey")),
    )
    op.create_index(
        "outbox_pending_idx", "outbox", ["id"], postgresql_where=sa.text("processed_at IS NULL")
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column(
            "args",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default="queued", nullable=False),
        sa.Column("attempts", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.SmallInteger(), server_default="5", nullable=False),
        sa.Column(
            "run_after",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("dedup_key", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'done', 'failed')", name=op.f("jobs_status_check")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("jobs_pkey")),
        sa.UniqueConstraint("dedup_key", name=op.f("jobs_dedup_key_key")),
    )
    op.create_index(
        "jobs_ready_idx", "jobs", ["run_after"], postgresql_where=sa.text("status = 'queued'")
    )


def downgrade() -> None:
    op.drop_index("jobs_ready_idx", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("outbox_pending_idx", table_name="outbox")
    op.drop_table("outbox")
