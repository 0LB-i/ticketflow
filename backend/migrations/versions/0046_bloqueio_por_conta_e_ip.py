"""Bloqueio do login por conta e IP: `login_ip_failures.user_id` marca as tentativas com a senha
errada de uma conta, e saem `users.failed_logins`, `last_failed_login_at` e `locked_until` (o
bloqueio valia para todos os IPs: quem atacava tirava o dono da conta).

O downgrade recria as colunas zeradas (nenhuma conta bloqueada).

Revision ID: 0046
Revises: 0045
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("login_ip_failures", sa.Column("user_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        op.f("login_ip_failures_user_id_fkey"),
        "login_ip_failures",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("login_ip_failures_user_id_idx", "login_ip_failures", ["user_id", "ip", "at"])
    op.drop_column("users", "locked_until")
    op.drop_column("users", "last_failed_login_at")
    op.drop_column("users", "failed_logins")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("failed_logins", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "users", sa.Column("last_failed_login_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("users", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.drop_index("login_ip_failures_user_id_idx", table_name="login_ip_failures")
    op.drop_constraint(
        op.f("login_ip_failures_user_id_fkey"), "login_ip_failures", type_="foreignkey"
    )
    op.drop_column("login_ip_failures", "user_id")
