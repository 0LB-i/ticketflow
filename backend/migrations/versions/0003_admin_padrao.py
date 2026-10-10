"""Login por nome de usuário, troca obrigatória de senha e administrador padrão admin/admin.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from argon2 import PasswordHasher
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("username", postgresql.CITEXT(), nullable=True))
    op.create_unique_constraint(op.f("users_username_key"), "users", ["username"])
    op.add_column(
        "users",
        sa.Column(
            "must_change_password", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    op.alter_column("users", "email", existing_type=postgresql.CITEXT(), nullable=True)
    op.create_check_constraint(
        op.f("users_login_check"), "users", "email IS NOT NULL OR username IS NOT NULL"
    )

    # Administrador padrão (docs/09 §9.2): entra com admin/admin e troca a senha na hora.
    # Só é criado se ainda não houver um usuário "admin".
    op.execute(
        sa.text(
            """
            INSERT INTO users (username, full_name, role_id, password_hash, must_change_password)
            SELECT 'admin', 'Administrador', r.id, :hash, true
            FROM roles r
            WHERE r.code = 'admin' AND NOT EXISTS (SELECT 1 FROM users WHERE username = 'admin')
            """
        ).bindparams(hash=PasswordHasher().hash("admin"))
    )


def downgrade() -> None:
    # Usuários sem e-mail não cabem no schema anterior.
    op.execute(
        "UPDATE audit_log SET actor_user_id = NULL "
        "WHERE actor_user_id IN (SELECT id FROM users WHERE email IS NULL)"
    )
    op.execute("DELETE FROM users WHERE email IS NULL")
    op.drop_constraint(op.f("users_login_check"), "users", type_="check")
    op.alter_column("users", "email", existing_type=postgresql.CITEXT(), nullable=False)
    op.drop_column("users", "must_change_password")
    op.drop_constraint(op.f("users_username_key"), "users", type_="unique")
    op.drop_column("users", "username")
