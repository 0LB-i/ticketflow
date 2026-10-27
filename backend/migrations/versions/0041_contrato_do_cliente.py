"""Contrato do cliente: `clients.contract_type` (mensal, anual ou chamado avulso) e
`clients.contract_hours` (as horas contratadas por mês ou por ano; só no mensal e no anual).
Os clientes que já existem ficam sem contrato informado.

Revision ID: 0041
Revises: 0040
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("contract_type", sa.Text()))
    op.add_column("clients", sa.Column("contract_hours", sa.Integer()))
    op.create_check_constraint(
        op.f("clients_contract_type_check"),
        "clients",
        "contract_type IN ('monthly', 'annual', 'on_demand')",
    )
    op.create_check_constraint(
        op.f("clients_contract_hours_check"),
        "clients",
        "contract_hours IS NULL OR (contract_type IN ('monthly', 'annual') AND contract_hours > 0)",
    )


def downgrade() -> None:
    op.drop_column("clients", "contract_hours")
    op.drop_column("clients", "contract_type")
