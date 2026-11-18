"""Permissões por área nos tokens de API: `api_tokens.permissions` no lugar de `scope`.

Os tokens que já existem ficam com o mesmo acesso de antes (`identity/token_access.py`): `read`
lê os chamados e os relatórios; `write` também cria, edita e remove nos chamados. O downgrade
volta a `write` quem tem alguma permissão além de ver, e a `read` os outros.

Revision ID: 0051
Revises: 0050
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0051"
down_revision: str | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

READ_ONLY = "{tickets.view,reports.view}"
READ_WRITE = "{tickets.view,tickets.create,tickets.edit,tickets.delete,reports.view}"


def upgrade() -> None:
    op.add_column(
        "api_tokens",
        sa.Column(
            "permissions",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    op.execute(
        "UPDATE api_tokens SET permissions = CASE scope "
        f"WHEN 'write' THEN '{READ_WRITE}'::text[] ELSE '{READ_ONLY}'::text[] END"
    )
    op.drop_constraint(op.f("api_tokens_scope_check"), "api_tokens", type_="check")
    op.drop_column("api_tokens", "scope")


def downgrade() -> None:
    op.add_column(
        "api_tokens", sa.Column("scope", sa.Text(), server_default="read", nullable=False)
    )
    op.execute(
        "UPDATE api_tokens SET scope = 'write' WHERE EXISTS "
        "(SELECT 1 FROM unnest(permissions) p WHERE p NOT LIKE '%.view')"
    )
    op.alter_column("api_tokens", "scope", server_default=None)
    op.create_check_constraint(
        op.f("api_tokens_scope_check"), "api_tokens", "scope IN ('read', 'write')"
    )
    op.drop_column("api_tokens", "permissions")
