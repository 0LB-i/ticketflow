"""appointments e appointment_attendees: a agenda (ARCHITECTURE 3.7.3).

Cada compromisso tem o dono, o período, o chamado (opcional) e os participantes, com a hora em
que cada um viu o aviso de 15 minutos antes.

Revision ID: 0049
Revises: 0048
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "appointments",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "public_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("all_day", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("ticket_id", sa.BigInteger(), nullable=True),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
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
        sa.CheckConstraint("ends_at > starts_at", name=op.f("appointments_period_check")),
        sa.CheckConstraint(
            "length(title) BETWEEN 1 AND 200", name=op.f("appointments_title_check")
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("appointments_owner_id_fkey")
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["tickets.id"], name=op.f("appointments_ticket_id_fkey")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("appointments_pkey")),
        sa.UniqueConstraint("public_id", name=op.f("appointments_public_id_key")),
    )
    op.create_index(op.f("appointments_ticket_id_idx"), "appointments", ["ticket_id"], unique=False)
    op.create_table(
        "appointment_attendees",
        sa.Column("appointment_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("alert_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["appointment_id"],
            ["appointments.id"],
            name=op.f("appointment_attendees_appointment_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("appointment_attendees_user_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "appointment_id", "user_id", name=op.f("appointment_attendees_pkey")
        ),
    )
    op.create_index(
        "appointment_attendees_user_idx",
        "appointment_attendees",
        ["user_id", "appointment_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("appointment_attendees_user_idx", table_name="appointment_attendees")
    op.drop_table("appointment_attendees")
    op.drop_index(op.f("appointments_ticket_id_idx"), table_name="appointments")
    op.drop_table("appointments")
