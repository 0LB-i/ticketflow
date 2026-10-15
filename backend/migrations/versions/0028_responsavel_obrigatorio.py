"""Chamado: o responsável é obrigatório (sem fila de não atribuídos, pedido do usuário).

O cliente também passa a ser obrigatório, mas só na API: chamados antigos sem cliente continuam.

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("tickets", "assignee_id", nullable=False)


def downgrade() -> None:
    op.alter_column("tickets", "assignee_id", nullable=True)
