"""Sem prioridade: saem priority, priority_overridden, impact, urgency e ticket.set_priority.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Permissões retiradas dos papéis do sistema (o teste de permissões desconta das da 0002).
REMOVED_PERMISSIONS = {"agent": ["ticket.set_priority"], "admin": ["ticket.set_priority"]}


def upgrade() -> None:
    op.drop_index("tickets_queue_idx", table_name="tickets")
    for column in ("priority", "priority_overridden", "impact", "urgency"):
        op.drop_column("tickets", column)  # leva junto o CHECK da coluna
    op.create_index(
        "tickets_queue_idx", "tickets", ["team_id", "status_id", "created_at"], unique=False
    )
    # Também dos papéis criados pelo admin.
    op.execute("UPDATE roles SET permissions = array_remove(permissions, 'ticket.set_priority')")


def downgrade() -> None:
    for code in REMOVED_PERMISSIONS:
        op.execute(
            sa.text(
                "UPDATE roles SET permissions = permissions || 'ticket.set_priority'::text "
                "WHERE code = :code"
            ).bindparams(code=code)
        )
    op.drop_index("tickets_queue_idx", table_name="tickets")
    # Chamados existentes voltam como impacto 1 × urgência 1 (prioridade baixa).
    for column in ("impact", "urgency", "priority"):
        op.add_column(
            "tickets",
            sa.Column(column, sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        )
        op.alter_column("tickets", column, server_default=None)
    op.add_column(
        "tickets",
        sa.Column(
            "priority_overridden", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    op.create_check_constraint(op.f("tickets_impact_check"), "tickets", "impact BETWEEN 1 AND 3")
    op.create_check_constraint(op.f("tickets_urgency_check"), "tickets", "urgency BETWEEN 1 AND 3")
    op.create_check_constraint(
        op.f("tickets_priority_check"), "tickets", "priority BETWEEN 1 AND 4"
    )
    op.create_index(
        "tickets_queue_idx",
        "tickets",
        ["team_id", "status_id", sa.literal_column("priority DESC"), "created_at"],
        unique=False,
    )
