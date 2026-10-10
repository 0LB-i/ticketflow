"""O status "Aguardando" passa a se chamar "Aguardando cliente".

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE ticket_statuses SET name = 'Aguardando cliente' WHERE name = 'Aguardando'")


def downgrade() -> None:
    op.execute("UPDATE ticket_statuses SET name = 'Aguardando' WHERE name = 'Aguardando cliente'")
