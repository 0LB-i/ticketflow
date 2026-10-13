"""Mais de um responsável por chamado (ticket_co_assignees) e ticket.assign_others para o agente.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Permissões novas de cada papel do sistema (o teste de permissões soma com as da 0002 e 0010).
# Antes, o agente só atribuía a outro membro nos grupos que supervisiona.
NEW_PERMISSIONS = {"agent": ["ticket.assign_others"]}


def upgrade() -> None:
    op.create_table(
        "ticket_co_assignees",
        sa.Column("ticket_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            name=op.f("ticket_co_assignees_ticket_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("ticket_co_assignees_user_id_fkey")
        ),
        sa.PrimaryKeyConstraint("ticket_id", "user_id", name=op.f("ticket_co_assignees_pkey")),
    )
    op.create_index(
        op.f("ticket_co_assignees_user_id_idx"), "ticket_co_assignees", ["user_id"], unique=False
    )
    for code, permissions in NEW_PERMISSIONS.items():
        op.execute(
            sa.text(
                "UPDATE roles SET permissions = permissions || :p WHERE code = :code"
            ).bindparams(
                sa.bindparam("p", permissions, type_=postgresql.ARRAY(sa.Text())), code=code
            )
        )


def downgrade() -> None:
    for code, permissions in NEW_PERMISSIONS.items():
        for permission in permissions:
            op.execute(
                sa.text(
                    "UPDATE roles SET permissions = array_remove(permissions, :p) "
                    "WHERE code = :code"
                ).bindparams(p=permission, code=code)
            )
    op.drop_index(op.f("ticket_co_assignees_user_id_idx"), table_name="ticket_co_assignees")
    op.drop_table("ticket_co_assignees")
