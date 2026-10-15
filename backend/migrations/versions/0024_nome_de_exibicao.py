"""Nome de exibição: users.display_name.

É o nome que aparece no sistema (chamados, tarefas, horas, grupos, menções, menu, e-mails);
o nome completo (full_name) fica no cadastro. Quem já existe começa com o nome completo.

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("display_name", sa.Text()))
    op.execute("UPDATE users SET display_name = full_name")
    op.alter_column("users", "display_name", nullable=False)


def downgrade() -> None:
    op.drop_column("users", "display_name")
