"""Grupo padrão "Administradores", com o administrador padrão admin como membro.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Todo usuário é membro de pelo menos um grupo (docs/08 §8.1), inclusive o admin padrão.
    # Não recria o grupo nem o vínculo se já existirem.
    op.execute(
        """
        INSERT INTO teams (name, description)
        VALUES ('Administradores', 'Responsáveis pelo sistema')
        ON CONFLICT (name) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO team_members (team_id, user_id)
        SELECT t.id, u.id
        FROM teams t, users u
        WHERE t.name = 'Administradores' AND u.username = 'admin'
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    # O grupo fica: pode já ter chamados, e grupos não são apagados, só desativados.
    pass
