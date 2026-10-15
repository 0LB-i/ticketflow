"""Cliente: só CEP, cidade e UF obrigatórios; vários telefones e e-mails.

Telefone e celular viram a lista `phones`; o e-mail vira a lista `emails`. Nome, CPF/CNPJ,
logradouro, número e bairro passam a ser opcionais.

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OPTIONAL = ("name", "document", "street", "number", "district")


def upgrade() -> None:
    for column in ("emails", "phones"):
        op.add_column(
            "clients",
            sa.Column(
                column,
                postgresql.ARRAY(sa.Text()),
                server_default=sa.text("'{}'"),
                nullable=False,
            ),
        )
    op.execute(
        "UPDATE clients SET emails = ARRAY[email],"
        " phones = array_remove(ARRAY[phone, mobile], NULL)"
    )
    for column in ("email", "phone", "mobile"):
        op.drop_column("clients", column)
    for column in OPTIONAL:
        op.alter_column("clients", column, nullable=True)


def downgrade() -> None:
    for column in ("email", "phone", "mobile"):
        op.add_column("clients", sa.Column(column, sa.Text()))
    op.execute(
        "UPDATE clients SET email = coalesce(emails[1], ''), phone = coalesce(phones[1], ''),"
        " mobile = phones[2]"
    )
    op.alter_column("clients", "email", nullable=False)
    op.alter_column("clients", "phone", nullable=False)
    op.drop_column("clients", "phones")
    op.drop_column("clients", "emails")
    # Sem CPF/CNPJ, um marcador único para voltar a ser obrigatório.
    op.execute("UPDATE clients SET document = 'SEM-' || public_id WHERE document IS NULL")
    for column in OPTIONAL:
        op.execute(f"UPDATE clients SET {column} = '' WHERE {column} IS NULL")
        op.alter_column("clients", column, nullable=False)
