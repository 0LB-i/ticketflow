"""teams.manages_clients: o acesso aos clientes vem de uma marca no grupo, não do nome dele.

Até aqui, client.view e client.manage valiam para os membros do grupo ativo chamado
"Administradores" (sem maiúsculas nem espaços nas pontas), e renomear o grupo tirava o acesso de
todos. A migração marca esse grupo; não há tela nem campo na API para mudar a marca.

Revision ID: 0048
Revises: 0047
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "teams",
        sa.Column("manages_clients", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.execute(
        "UPDATE teams SET manages_clients = true WHERE lower(btrim(name)) = 'administradores'"
    )


def downgrade() -> None:
    op.drop_column("teams", "manages_clients")
