"""Papel Cliente: quem é de uma empresa atendida e só vê o painel dela (docs/08). O papel do
sistema `client`, sem nenhuma permissão, e `users.client_id`, a empresa (o cadastro de clientes)
de quem tem esse papel.

O downgrade passa quem tem o papel Cliente a Agente inativo (sem acesso) antes de tirar o papel.

Revision ID: 0045
Revises: 0044
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SYSTEM_ROLES = [("client", "Cliente", [])]


def upgrade() -> None:
    roles = sa.table(
        "roles",
        sa.column("code", sa.Text),
        sa.column("name", sa.Text),
        sa.column("permissions", sa.ARRAY(sa.Text)),
        sa.column("is_system", sa.Boolean),
    )
    op.bulk_insert(
        roles,
        [
            {"code": code, "name": name, "permissions": perms, "is_system": True}
            for code, name, perms in SYSTEM_ROLES
        ],
    )
    op.add_column("users", sa.Column("client_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(op.f("users_client_id_fkey"), "users", "clients", ["client_id"], ["id"])
    op.create_index(op.f("users_client_id_idx"), "users", ["client_id"])


def downgrade() -> None:
    op.execute(
        """
        UPDATE users
           SET role_id = (SELECT id FROM roles WHERE code = 'agent'), is_active = false
         WHERE role_id = (SELECT id FROM roles WHERE code = 'client')
        """
    )
    op.drop_index(op.f("users_client_id_idx"), table_name="users")
    op.drop_constraint(op.f("users_client_id_fkey"), "users", type_="foreignkey")
    op.drop_column("users", "client_id")
    op.execute("DELETE FROM roles WHERE code = 'client'")
