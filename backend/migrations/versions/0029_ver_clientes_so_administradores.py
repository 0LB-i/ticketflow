"""Cliente: client.view também sai dos papéis; vale só para membros do grupo Administradores.

O cadastro (documentos, contatos, endereço) fica só com eles (pedido do usuário). Para escolher
o cliente de um chamado, todos usam GET /clients/options, que devolve só o nome.

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Permissões retiradas dos papéis do sistema (o teste de permissões desconta das da 0002).
REMOVED_PERMISSIONS = {
    "agent": ["client.view"],
    "admin": ["client.view"],
    "auditor": ["client.view"],
}


def upgrade() -> None:
    op.execute("UPDATE roles SET permissions = array_remove(permissions, 'client.view')")


def downgrade() -> None:
    for code in REMOVED_PERMISSIONS:
        op.execute(
            sa.text(
                "UPDATE roles SET permissions = permissions || 'client.view'::text "
                "WHERE code = :code"
            ).bindparams(code=code)
        )
