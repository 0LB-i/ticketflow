"""Cadastro de clientes (pessoa física e jurídica) e as permissões client.view e client.manage.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Permissões novas de cada papel do sistema (o teste de permissões soma com as da 0002).
NEW_PERMISSIONS = {
    "agent": ["client.view", "client.manage"],
    "admin": ["client.view", "client.manage"],
    "auditor": ["client.view"],
}


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "public_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("trade_name", sa.Text(), nullable=True),
        sa.Column("document", sa.Text(), nullable=False),
        sa.Column("id_number", sa.Text(), nullable=True),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("state_registration", sa.Text(), nullable=True),
        sa.Column("municipal_registration", sa.Text(), nullable=True),
        sa.Column("contact_name", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("phone", sa.Text(), nullable=False),
        sa.Column("mobile", sa.Text(), nullable=True),
        sa.Column("postal_code", sa.Text(), nullable=False),
        sa.Column("street", sa.Text(), nullable=False),
        sa.Column("number", sa.Text(), nullable=False),
        sa.Column("complement", sa.Text(), nullable=True),
        sa.Column("district", sa.Text(), nullable=False),
        sa.Column("city", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('person', 'company')", name=op.f("clients_kind_check")),
        sa.CheckConstraint("length(state) = 2", name=op.f("clients_state_check")),
        sa.PrimaryKeyConstraint("id", name=op.f("clients_pkey")),
        sa.UniqueConstraint("document", name=op.f("clients_document_key")),
        sa.UniqueConstraint("public_id", name=op.f("clients_public_id_key")),
    )
    op.create_index("clients_name_idx", "clients", [sa.text("lower(name)")])
    for code, permissions in NEW_PERMISSIONS.items():
        op.execute(
            sa.text(
                "UPDATE roles SET permissions = permissions || :p WHERE code = :code"
            ).bindparams(
                sa.bindparam("p", permissions, type_=postgresql.ARRAY(sa.Text())), code=code
            )
        )


def downgrade() -> None:
    for code, permissions in NEW_PERMISSIONS.items():
        for permission in permissions:
            op.execute(
                sa.text(
                    "UPDATE roles SET permissions = array_remove(permissions, :p) "
                    "WHERE code = :code"
                ).bindparams(p=permission, code=code)
            )
    op.drop_index("clients_name_idx", table_name="clients")
    op.drop_table("clients")
