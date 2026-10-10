"""Status "Entregue" (kind closed, não é o padrão do kind) entre Aguardando e Concluído.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE ticket_statuses SET sort_order = 4 WHERE name = 'Concluído'")
    op.execute("UPDATE ticket_statuses SET sort_order = 5 WHERE name = 'Cancelado'")
    op.execute(
        "INSERT INTO ticket_statuses (name, kind, sort_order, is_default_for_kind) "
        "VALUES ('Entregue', 'closed', 3, false)"
    )


def downgrade() -> None:
    # Chamados entregues voltam para o status padrão do kind closed.
    op.execute(
        "UPDATE tickets SET status_id = (SELECT id FROM ticket_statuses "
        "WHERE kind = 'closed' AND is_default_for_kind) "
        "WHERE status_id = (SELECT id FROM ticket_statuses WHERE name = 'Entregue')"
    )
    op.execute("DELETE FROM ticket_statuses WHERE name = 'Entregue'")
    op.execute("UPDATE ticket_statuses SET sort_order = 3 WHERE name = 'Concluído'")
    op.execute("UPDATE ticket_statuses SET sort_order = 4 WHERE name = 'Cancelado'")
