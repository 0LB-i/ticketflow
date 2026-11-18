"""Perfil do usuário: telefone, cargo e foto (`users.phone`, `job_title`, `avatar`, `avatar_hash`).

Revision ID: 0052
Revises: 0051
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0052"
down_revision: str | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("phone", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("job_title", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("avatar", postgresql.BYTEA(), nullable=True))
    op.add_column("users", sa.Column("avatar_hash", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "avatar_hash")
    op.drop_column("users", "avatar")
    op.drop_column("users", "job_title")
    op.drop_column("users", "phone")
