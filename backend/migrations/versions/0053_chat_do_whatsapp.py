"""Chat do WhatsApp: números (canais) com os responsáveis, conversas e mensagens.

Revision ID: 0053
Revises: 0052
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0053"
down_revision: str | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "whatsapp_channels",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "public_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), server_default=sa.text("'new'"), nullable=False),
        sa.Column("sign_messages", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.CheckConstraint(
            "state IN ('new', 'pairing', 'connected', 'disconnected', 'logged_out')",
            name=op.f("whatsapp_channels_state_check"),
        ),
        sa.CheckConstraint(
            "length(name) BETWEEN 1 AND 100", name=op.f("whatsapp_channels_name_check")
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], name=op.f("whatsapp_channels_team_id_fkey")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("whatsapp_channels_pkey")),
        sa.UniqueConstraint("public_id", name=op.f("whatsapp_channels_public_id_key")),
    )
    op.create_index(
        op.f("whatsapp_channels_team_id_idx"), "whatsapp_channels", ["team_id"], unique=False
    )
    op.create_table(
        "whatsapp_channel_managers",
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["whatsapp_channels.id"],
            name=op.f("whatsapp_channel_managers_channel_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("whatsapp_channel_managers_user_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "channel_id", "user_id", name=op.f("whatsapp_channel_managers_pkey")
        ),
    )
    op.create_index(
        op.f("whatsapp_channel_managers_user_id_idx"),
        "whatsapp_channel_managers",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "whatsapp_chats",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "public_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("jid", sa.Text(), nullable=False),
        sa.Column("is_group", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("unread", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["whatsapp_channels.id"],
            name=op.f("whatsapp_chats_channel_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("whatsapp_chats_pkey")),
        sa.UniqueConstraint("channel_id", "jid", name=op.f("whatsapp_chats_channel_id_jid_key")),
        sa.UniqueConstraint("public_id", name=op.f("whatsapp_chats_public_id_key")),
    )
    op.create_index(
        "whatsapp_chats_recent_idx",
        "whatsapp_chats",
        ["channel_id", sa.literal_column("last_message_at DESC NULLS LAST")],
        unique=False,
    )
    op.create_table(
        "whatsapp_messages",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("wa_id", sa.Text(), nullable=False),
        sa.Column("from_me", sa.Boolean(), nullable=False),
        sa.Column("author_id", sa.BigInteger(), nullable=True),
        sa.Column("sender_jid", sa.Text(), nullable=True),
        sa.Column("sender_name", sa.Text(), nullable=True),
        sa.Column("kind", sa.Text(), server_default=sa.text("'text'"), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("file_name", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('text', 'image', 'video', 'gif', 'audio', 'voice', 'document', 'sticker',"
            " 'location', 'contact', 'poll', 'other')",
            name=op.f("whatsapp_messages_kind_check"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'received')",
            name=op.f("whatsapp_messages_status_check"),
        ),
        sa.ForeignKeyConstraint(
            ["author_id"], ["users.id"], name=op.f("whatsapp_messages_author_id_fkey")
        ),
        sa.ForeignKeyConstraint(
            ["chat_id"],
            ["whatsapp_chats.id"],
            name=op.f("whatsapp_messages_chat_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("whatsapp_messages_pkey")),
        sa.UniqueConstraint("chat_id", "wa_id", name=op.f("whatsapp_messages_chat_id_wa_id_key")),
    )
    op.create_index(
        "whatsapp_messages_chat_idx",
        "whatsapp_messages",
        ["chat_id", sa.literal_column("sent_at DESC"), sa.literal_column("id DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("whatsapp_messages_chat_idx", table_name="whatsapp_messages")
    op.drop_table("whatsapp_messages")
    op.drop_index("whatsapp_chats_recent_idx", table_name="whatsapp_chats")
    op.drop_table("whatsapp_chats")
    op.drop_index(
        op.f("whatsapp_channel_managers_user_id_idx"), table_name="whatsapp_channel_managers"
    )
    op.drop_table("whatsapp_channel_managers")
    op.drop_index(op.f("whatsapp_channels_team_id_idx"), table_name="whatsapp_channels")
    op.drop_table("whatsapp_channels")
