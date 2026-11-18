"""Chat do WhatsApp: o arquivo de cada mensagem (`media_path`, `mime_type`, `file_size`) e os
ticks de entregue e lida (`status`).

Revision ID: 0054
Revises: 0053
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0054"
down_revision: str | None = "0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "status IN ('pending', 'sent', 'failed', 'received')"
NEW = "status IN ('pending', 'sent', 'delivered', 'read', 'failed', 'received')"


def upgrade() -> None:
    op.add_column("whatsapp_messages", sa.Column("media_path", sa.Text(), nullable=True))
    op.add_column("whatsapp_messages", sa.Column("mime_type", sa.Text(), nullable=True))
    op.add_column("whatsapp_messages", sa.Column("file_size", sa.BigInteger(), nullable=True))
    op.drop_constraint(op.f("whatsapp_messages_status_check"), "whatsapp_messages", type_="check")
    op.create_check_constraint(op.f("whatsapp_messages_status_check"), "whatsapp_messages", NEW)


def downgrade() -> None:
    op.execute("UPDATE whatsapp_messages SET status = 'sent' WHERE status IN ('delivered', 'read')")
    op.drop_constraint(op.f("whatsapp_messages_status_check"), "whatsapp_messages", type_="check")
    op.create_check_constraint(op.f("whatsapp_messages_status_check"), "whatsapp_messages", OLD)
    op.drop_column("whatsapp_messages", "file_size")
    op.drop_column("whatsapp_messages", "mime_type")
    op.drop_column("whatsapp_messages", "media_path")
