"""Categorias, status, códigos de resolução e chamados (Sprint 3: docs/08, docs/10).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Status padrão (docs/10 §10.5): nome, kind, ordem. O admin cria outros na Sprint 5.
STATUSES = [
    ("Pendente", "open", 1),
    ("Aguardando", "waiting", 2),
    ("Concluído", "closed", 3),
    ("Cancelado", "canceled", 4),
]
RESOLUTION_CODES = [
    "Feito",
    "Feito com solução de contorno",
    "Não reproduzível",
    "Fora do escopo do grupo",
]


def upgrade() -> None:
    op.create_table(
        "resolution_codes",
        sa.Column("id", sa.SmallInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("resolution_codes_pkey")),
        sa.UniqueConstraint("name", name=op.f("resolution_codes_name_key")),
    )
    op.bulk_insert(
        sa.table("resolution_codes", sa.column("name", sa.Text)),
        [{"name": name} for name in RESOLUTION_CODES],
    )
    op.create_table(
        "ticket_statuses",
        sa.Column("id", sa.SmallInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "is_default_for_kind", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('approval', 'open', 'waiting', 'closed', 'canceled')",
            name=op.f("ticket_statuses_kind_check"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("ticket_statuses_pkey")),
        sa.UniqueConstraint("name", name=op.f("ticket_statuses_name_key")),
    )
    op.create_index(
        "ticket_statuses_default_idx",
        "ticket_statuses",
        ["kind"],
        unique=True,
        postgresql_where=sa.text("is_default_for_kind"),
    )
    op.bulk_insert(
        sa.table(
            "ticket_statuses",
            sa.column("name", sa.Text),
            sa.column("kind", sa.Text),
            sa.column("sort_order", sa.SmallInteger),
            sa.column("is_default_for_kind", sa.Boolean),
        ),
        [
            {"name": name, "kind": kind, "sort_order": order, "is_default_for_kind": True}
            for name, kind, order in STATUSES
        ],
    )
    op.create_table(
        "categories",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "public_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("default_team_id", sa.BigInteger(), nullable=True),
        sa.Column("default_type", sa.Text(), server_default=sa.text("'incident'"), nullable=False),
        sa.Column("is_confidential", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "default_type IN ('incident', 'request', 'task')",
            name=op.f("categories_default_type_check"),
        ),
        sa.ForeignKeyConstraint(
            ["default_team_id"], ["teams.id"], name=op.f("categories_default_team_id_fkey")
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["categories.id"], name=op.f("categories_parent_id_fkey")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("categories_pkey")),
        sa.UniqueConstraint(
            "parent_id",
            "name",
            name=op.f("categories_parent_id_name_key"),
            postgresql_nulls_not_distinct=True,
        ),
        sa.UniqueConstraint("public_id", name=op.f("categories_public_id_key")),
    )
    # Número legível do chamado (#1234), nunca reutilizado.
    op.execute("CREATE SEQUENCE ticket_number_seq START WITH 1000")
    op.create_table(
        "tickets",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "public_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "number",
            sa.BigInteger(),
            server_default=sa.text("nextval('ticket_number_seq')"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("created_by_id", sa.BigInteger(), nullable=False),
        sa.Column("department_id", sa.BigInteger(), nullable=True),
        sa.Column("beneficiary_name", sa.Text(), nullable=True),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("assignee_id", sa.BigInteger(), nullable=True),
        sa.Column("category_id", sa.BigInteger(), nullable=False),
        sa.Column("status_id", sa.SmallInteger(), nullable=False),
        sa.Column("impact", sa.SmallInteger(), nullable=False),
        sa.Column("urgency", sa.SmallInteger(), nullable=False),
        sa.Column("priority", sa.SmallInteger(), nullable=False),
        sa.Column(
            "priority_overridden", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("resolution_code_id", sa.SmallInteger(), nullable=True),
        sa.Column("reopened_count", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
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
        sa.Column("first_assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "type IN ('incident', 'request', 'task')", name=op.f("tickets_type_check")
        ),
        sa.CheckConstraint("impact BETWEEN 1 AND 3", name=op.f("tickets_impact_check")),
        sa.CheckConstraint("length(title) BETWEEN 3 AND 300", name=op.f("tickets_title_check")),
        sa.CheckConstraint("priority BETWEEN 1 AND 4", name=op.f("tickets_priority_check")),
        sa.CheckConstraint("urgency BETWEEN 1 AND 3", name=op.f("tickets_urgency_check")),
        sa.ForeignKeyConstraint(
            ["assignee_id"], ["users.id"], name=op.f("tickets_assignee_id_fkey")
        ),
        sa.ForeignKeyConstraint(
            ["category_id"], ["categories.id"], name=op.f("tickets_category_id_fkey")
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], name=op.f("tickets_created_by_id_fkey")
        ),
        sa.ForeignKeyConstraint(
            ["department_id"], ["departments.id"], name=op.f("tickets_department_id_fkey")
        ),
        sa.ForeignKeyConstraint(
            ["resolution_code_id"],
            ["resolution_codes.id"],
            name=op.f("tickets_resolution_code_id_fkey"),
        ),
        sa.ForeignKeyConstraint(
            ["status_id"], ["ticket_statuses.id"], name=op.f("tickets_status_id_fkey")
        ),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], name=op.f("tickets_team_id_fkey")),
        sa.PrimaryKeyConstraint("id", name=op.f("tickets_pkey")),
        sa.UniqueConstraint("number", name=op.f("tickets_number_key")),
        sa.UniqueConstraint("public_id", name=op.f("tickets_public_id_key")),
    )
    op.execute("ALTER SEQUENCE ticket_number_seq OWNED BY tickets.number")
    op.create_index("tickets_assignee_idx", "tickets", ["assignee_id", "status_id"], unique=False)
    op.create_index(
        "tickets_queue_idx",
        "tickets",
        ["team_id", "status_id", sa.literal_column("priority DESC"), "created_at"],
        unique=False,
    )
    op.create_table(
        "ticket_comments",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "public_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("ticket_id", sa.BigInteger(), nullable=False),
        sa.Column("author_id", sa.BigInteger(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_solution", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("length(body) > 0", name=op.f("ticket_comments_body_check")),
        sa.ForeignKeyConstraint(
            ["author_id"], ["users.id"], name=op.f("ticket_comments_author_id_fkey")
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            name=op.f("ticket_comments_ticket_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("ticket_comments_pkey")),
        sa.UniqueConstraint("public_id", name=op.f("ticket_comments_public_id_key")),
    )
    op.create_index(
        "ticket_comments_ticket_idx", "ticket_comments", ["ticket_id", "created_at"], unique=False
    )
    op.create_table(
        "ticket_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("ticket_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], name=op.f("ticket_events_actor_user_id_fkey")
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            name=op.f("ticket_events_ticket_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("ticket_events_pkey")),
    )
    op.create_index(
        "ticket_events_ticket_idx", "ticket_events", ["ticket_id", "created_at"], unique=False
    )
    # Histórico só aceita inserção (docs/04). O TRUNCATE dos testes não dispara a trigger.
    op.execute(
        """
        CREATE FUNCTION ticket_events_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'ticket_events só aceita inserção';
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER ticket_events_append_only BEFORE UPDATE OR DELETE ON ticket_events "
        "FOR EACH ROW EXECUTE FUNCTION ticket_events_append_only()"
    )
    op.create_table(
        "ticket_teams",
        sa.Column("ticket_id", sa.BigInteger(), nullable=False),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "first_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], name=op.f("ticket_teams_team_id_fkey")),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            name=op.f("ticket_teams_ticket_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("ticket_id", "team_id", name=op.f("ticket_teams_pkey")),
    )
    op.create_index(op.f("ticket_teams_team_id_idx"), "ticket_teams", ["team_id"], unique=False)
    op.create_table(
        "ticket_watchers",
        sa.Column("ticket_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), server_default=sa.text("'watcher'"), nullable=False),
        sa.Column("added_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('watcher', 'mentioned')", name=op.f("ticket_watchers_kind_check")
        ),
        sa.ForeignKeyConstraint(
            ["added_by"], ["users.id"], name=op.f("ticket_watchers_added_by_fkey")
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            name=op.f("ticket_watchers_ticket_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("ticket_watchers_user_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("ticket_id", "user_id", name=op.f("ticket_watchers_pkey")),
    )
    op.create_index(
        op.f("ticket_watchers_user_id_idx"), "ticket_watchers", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ticket_watchers_user_id_idx"), table_name="ticket_watchers")
    op.drop_table("ticket_watchers")
    op.drop_index(op.f("ticket_teams_team_id_idx"), table_name="ticket_teams")
    op.drop_table("ticket_teams")
    op.drop_index("ticket_events_ticket_idx", table_name="ticket_events")
    op.drop_table("ticket_events")
    op.execute("DROP FUNCTION ticket_events_append_only()")
    op.drop_index("ticket_comments_ticket_idx", table_name="ticket_comments")
    op.drop_table("ticket_comments")
    op.drop_index("tickets_queue_idx", table_name="tickets")
    op.drop_index("tickets_assignee_idx", table_name="tickets")
    op.drop_table("tickets")
    op.drop_table("categories")
    op.drop_index("ticket_statuses_default_idx", table_name="ticket_statuses")
    op.drop_table("ticket_statuses")
    op.drop_table("resolution_codes")
