"""Cliente: o mesmo CPF/CNPJ pode aparecer em mais de um cadastro.

Sai a restrição única de clients.document (pedido do usuário). O documento continua validado.

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("clients_document_key"), "clients", type_="unique")


def downgrade() -> None:
    # Falha se já houver documentos repetidos: resolva-os antes de voltar.
    op.create_unique_constraint(op.f("clients_document_key"), "clients", ["document"])
