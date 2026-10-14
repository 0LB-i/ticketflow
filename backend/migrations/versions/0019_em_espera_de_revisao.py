"""Status "Em espera de revisão" (kind waiting): o supervisor verifica antes de concluir.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ticket_statuses",
        sa.Column("is_review", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    # Logo depois de "Aguardando cliente" (ou no fim, se ele foi renomeado ou removido).
    op.execute(
        """
        WITH depois AS (
            SELECT coalesce(
                (SELECT sort_order FROM ticket_statuses WHERE name = 'Aguardando cliente'),
                (SELECT max(sort_order) FROM ticket_statuses)
            ) AS ordem
        ), abre AS (
            UPDATE ticket_statuses SET sort_order = sort_order + 1
            WHERE sort_order > (SELECT ordem FROM depois)
        )
        INSERT INTO ticket_statuses (name, kind, sort_order, is_default_for_kind, is_review)
        SELECT 'Em espera de revisão', 'waiting', ordem + 1, false, true FROM depois
        ON CONFLICT (name) DO UPDATE SET is_review = true
        """
    )


def downgrade() -> None:
    # Chamados em revisão voltam para o status padrão do kind waiting.
    op.execute(
        "UPDATE tickets SET status_id = (SELECT id FROM ticket_statuses "
        "WHERE kind = 'waiting' AND is_default_for_kind) "
        "WHERE status_id IN (SELECT id FROM ticket_statuses WHERE is_review)"
    )
    op.execute("DELETE FROM ticket_statuses WHERE is_review AND NOT is_default_for_kind")
    op.drop_column("ticket_statuses", "is_review")
