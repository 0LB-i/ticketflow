"""Cliente: client.manage sai dos papéis; vale só para membros do grupo Administradores.

A permissão passa a ser dada pelo grupo (core/permissions.py, pedido do usuário), então nenhum
papel a guarda mais.

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Permissões retiradas dos papéis do sistema (o teste de permissões desconta das da 0002).
REMOVED_PERMISSIONS = {"agent": ["client.manage"], "admin": ["client.manage"]}


def upgrade() -> None:
    op.execute("UPDATE roles SET permissions = array_remove(permissions, 'client.manage')")


def downgrade() -> None:
    for code in REMOVED_PERMISSIONS:
        op.execute(
            sa.text(
                "UPDATE roles SET permissions = permissions || 'client.manage'::text "
                "WHERE code = :code"
            ).bindparams(code=code)
        )
