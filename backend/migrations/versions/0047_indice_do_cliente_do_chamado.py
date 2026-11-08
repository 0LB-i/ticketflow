"""Índice `tickets_client_idx` (`client_id`): os chamados de um cliente.

O painel do papel Cliente, o filtro por cliente dos relatórios e o plano do cliente filtram por
ele; sem o índice, cada consulta lia a tabela de chamados inteira (benchmark, ARCHITECTURE.md §7.1).

Revision ID: 0047
Revises: 0046
Create Date: 2026-11-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("tickets_client_idx", "tickets", ["client_id"])


def downgrade() -> None:
    op.drop_index("tickets_client_idx", table_name="tickets")
