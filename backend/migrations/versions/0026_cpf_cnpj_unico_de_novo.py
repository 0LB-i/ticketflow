"""Cliente: CPF/CNPJ volta a ser único (desfaz a 0025, pedido do usuário).

Falha se já houver documentos repetidos: resolva-os antes de aplicar. O nome do cliente também
não pode repetir, mas essa regra fica na API (compara sem maiúsculas, acentos e espaços a mais).

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(op.f("clients_document_key"), "clients", ["document"])


def downgrade() -> None:
    op.drop_constraint(op.f("clients_document_key"), "clients", type_="unique")
