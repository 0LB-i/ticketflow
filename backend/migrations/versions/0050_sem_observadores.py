"""Sem observadores nem menções: apaga ticket_watchers e tira ticket.watch dos papéis.

Os eventos antigos (`watcher.added`, `watcher.removed`) continuam no histórico. O downgrade
recria a tabela vazia e devolve a permissão aos papéis Agente e Administrador.

Revision ID: 0050
Revises: 0049
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0050"
down_revision: str | None = "0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# O teste test_papeis_da_migracao_batem_com_o_catalogo tira estas da lista da migração base.
REMOVED_PERMISSIONS = ["ticket.watch"]


def upgrade() -> None:
    op.drop_table("ticket_watchers")
    op.execute(
        "UPDATE roles SET permissions = array_remove(permissions, 'ticket.watch') "
        "WHERE 'ticket.watch' = ANY(permissions)"
    )


def downgrade() -> None:
    op.create_table(
        "ticket_watchers",
        sa.Column("ticket_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), server_default=sa.text("'watcher'"), nullable=False),
        sa.Column("added_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('watcher', 'mentioned')", name=op.f("ticket_watchers_kind_check")
        ),
        sa.ForeignKeyConstraint(
            ["added_by"], ["users.id"], name=op.f("ticket_watchers_added_by_fkey")
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            name=op.f("ticket_watchers_ticket_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("ticket_watchers_user_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("ticket_id", "user_id", name=op.f("ticket_watchers_pkey")),
    )
    op.create_index(op.f("ticket_watchers_user_id_idx"), "ticket_watchers", ["user_id"])
    op.execute(
        "UPDATE roles SET permissions = array_append(permissions, 'ticket.watch') "
        "WHERE code IN ('agent', 'admin') AND is_system"
    )
