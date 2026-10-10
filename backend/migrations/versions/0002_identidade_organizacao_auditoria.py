"""Identidade, organização e auditoria (Sprint 2: docs/08 e docs/09).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Cópia do catálogo em core/permissions.py na data desta migração.
_AGENT = [
    "kb.read",
    "kb.write",
    "ticket.assign_self",
    "ticket.comment",
    "ticket.create",
    "ticket.edit",
    "ticket.merge",
    "ticket.set_priority",
    "ticket.transfer",
    "ticket.transition",
    "ticket.view_team",
    "ticket.watch",
]
_ALL = sorted(
    {
        *_AGENT,
        "ticket.view_all",
        "ticket.assign_others",
        "ticket.approve",
        "ticket.bulk",
        "ticket.hide_content",
        "ticket.export",
        "kb.publish",
        "report.view_team",
        "report.view_all",
        "admin.users",
        "admin.organization",
        "admin.catalog",
        "admin.settings",
        "audit.view",
    }
)
_AUDITOR = [
    "audit.view",
    "kb.read",
    "report.view_all",
    "report.view_team",
    "ticket.export",
    "ticket.view_all",
    "ticket.view_team",
]
SYSTEM_ROLES = [
    ("agent", "Agente", _AGENT),
    ("admin", "Administrador", _ALL),
    ("auditor", "Auditor", _AUDITOR),
]


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "public_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["departments.id"], name=op.f("departments_parent_id_fkey")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("departments_pkey")),
        sa.UniqueConstraint("code", name=op.f("departments_code_key")),
        sa.UniqueConstraint(
            "parent_id",
            "name",
            name=op.f("departments_parent_id_name_key"),
            postgresql_nulls_not_distinct=True,
        ),
        sa.UniqueConstraint("public_id", name=op.f("departments_public_id_key")),
    )
    op.create_table(
        "roles",
        sa.Column("id", sa.SmallInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("permissions", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("roles_pkey")),
        sa.UniqueConstraint("code", name=op.f("roles_code_key")),
    )
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
    op.create_table(
        "teams",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "public_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "notify_on_new", sa.Text(), server_default=sa.text("'queue_only'"), nullable=False
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "notify_on_new IN ('queue_only', 'email_all_members')",
            name=op.f("teams_notify_on_new_check"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("teams_pkey")),
        sa.UniqueConstraint("name", name=op.f("teams_name_key")),
        sa.UniqueConstraint("public_id", name=op.f("teams_public_id_key")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "public_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("role_id", sa.SmallInteger(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("failed_logins", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_failed_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], name=op.f("users_role_id_fkey")),
        sa.PrimaryKeyConstraint("id", name=op.f("users_pkey")),
        sa.UniqueConstraint("email", name=op.f("users_email_key")),
        sa.UniqueConstraint("public_id", name=op.f("users_public_id_key")),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("target_type", sa.Text(), nullable=True),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], name=op.f("audit_log_actor_user_id_fkey")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("audit_log_pkey")),
    )
    op.create_index(op.f("audit_log_created_at_idx"), "audit_log", ["created_at"], unique=False)
    op.create_index("audit_log_target_idx", "audit_log", ["target_type", "target_id"], unique=False)
    op.create_table(
        "auth_tokens",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "purpose IN ('invite', 'password_reset')", name=op.f("auth_tokens_purpose_check")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("auth_tokens_user_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("auth_tokens_pkey")),
        sa.UniqueConstraint("token_hash", name=op.f("auth_tokens_token_hash_key")),
    )
    op.create_index(op.f("auth_tokens_user_id_idx"), "auth_tokens", ["user_id"], unique=False)
    op.create_table(
        "team_members",
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.Text(), server_default=sa.text("'member'"), nullable=False),
        sa.Column("source", sa.Text(), server_default=sa.text("'manual'"), nullable=False),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "role IN ('member', 'supervisor')", name=op.f("team_members_role_check")
        ),
        sa.CheckConstraint("source IN ('manual', 'idp')", name=op.f("team_members_source_check")),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], name=op.f("team_members_team_id_fkey"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("team_members_user_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("team_id", "user_id", name=op.f("team_members_pkey")),
    )
    op.create_index(op.f("team_members_user_id_idx"), "team_members", ["user_id"], unique=False)
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("csrf_token_hash", sa.Text(), nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("user_sessions_user_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("user_sessions_pkey")),
        sa.UniqueConstraint("token_hash", name=op.f("user_sessions_token_hash_key")),
    )
    op.create_index(op.f("user_sessions_user_id_idx"), "user_sessions", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("user_sessions_user_id_idx"), table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_index(op.f("team_members_user_id_idx"), table_name="team_members")
    op.drop_table("team_members")
    op.drop_index(op.f("auth_tokens_user_id_idx"), table_name="auth_tokens")
    op.drop_table("auth_tokens")
    op.drop_index("audit_log_target_idx", table_name="audit_log")
    op.drop_index(op.f("audit_log_created_at_idx"), table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("users")
    op.drop_table("teams")
    op.drop_table("roles")
    op.drop_table("departments")
