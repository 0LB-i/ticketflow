"""Exclusão de usuário: users.deleted_at.

Excluir tira a pessoa do sistema (lista, grupos, login; e-mail livre para outro cadastro), mas
a linha fica: chamados, tarefas, horas e auditoria continuam mostrando o nome dela.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOGIN = "users_login_check"


def upgrade() -> None:
    op.add_column("users", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    # O excluído fica sem e-mail e sem nome de usuário.
    op.drop_constraint(op.f(LOGIN), "users", type_="check")
    op.create_check_constraint(
        op.f(LOGIN),
        "users",
        "deleted_at IS NOT NULL OR email IS NOT NULL OR username IS NOT NULL",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE users SET username = 'excluido-' || public_id"
        " WHERE deleted_at IS NOT NULL AND email IS NULL AND username IS NULL"
    )
    op.drop_constraint(op.f(LOGIN), "users", type_="check")
    op.create_check_constraint(op.f(LOGIN), "users", "email IS NOT NULL OR username IS NOT NULL")
    op.drop_column("users", "deleted_at")
