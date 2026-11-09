"""A base do schema em 2026-11-09: tudo o que as migrações 0001 a 0047 criavam, no estado final.

Uma instalação nova roda só esta migração, em vez das idas e voltas da cadeia antiga. Ela fica
com o id "0047" (o da última da cadeia): um banco que já estava na 0047 continua em dia, sem
nenhum comando. As próximas migrações se encadeiam a partir dela (0048, 0049…).

O histórico das migrações anteriores está no git até o commit
4ee5adaa0a2038ed50cd26757dfbbf43911d5364:

    git show 4ee5adaa0a2038ed50cd26757dfbbf43911d5364:backend/migrations/versions/

As colunas estão na ordem em que a cadeia as deixava (as acrescentadas depois ficam no fim da
tabela), para que o schema seja idêntico ao de um banco migrado por ela.

Revision ID: 0047
Revises:
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from argon2 import PasswordHasher
from sqlalchemy.dialects import postgresql

revision: str = "0047"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Papéis do sistema: código, nome e permissões, na ordem em que ficam gravadas. O teste
# test_papeis_da_migracao_batem_com_o_catalogo compara com `ROLES` (core/permissions.py).
SYSTEM_ROLES = [
    (
        "agent",
        "Agente",
        [
            "kb.read",
            "kb.write",
            "ticket.assign_self",
            "ticket.comment",
            "ticket.create",
            "ticket.edit",
            "ticket.merge",
            "ticket.transfer",
            "ticket.transition",
            "ticket.view_team",
            "ticket.watch",
            "ticket.assign_others",
        ],
    ),
    (
        "admin",
        "Administrador",
        [
            "admin.catalog",
            "admin.organization",
            "admin.settings",
            "admin.users",
            "audit.view",
            "kb.publish",
            "kb.read",
            "kb.write",
            "report.view_all",
            "report.view_team",
            "ticket.approve",
            "ticket.assign_others",
            "ticket.assign_self",
            "ticket.bulk",
            "ticket.comment",
            "ticket.create",
            "ticket.edit",
            "ticket.export",
            "ticket.hide_content",
            "ticket.merge",
            "ticket.transfer",
            "ticket.transition",
            "ticket.view_all",
            "ticket.view_team",
            "ticket.watch",
        ],
    ),
    (
        "auditor",
        "Auditor",
        [
            "audit.view",
            "kb.read",
            "report.view_all",
            "report.view_team",
            "ticket.export",
            "ticket.view_all",
            "ticket.view_team",
        ],
    ),
    ("client", "Cliente", []),
]
# Status padrão (docs/10 §10.5): id, nome, comportamento e ordem; todos são o padrão do
# comportamento. Os ids e a ordem são os que a cadeia antiga deixava (o 5 foi apagado nela).
STATUSES = [
    (1, "Pendente", "open", 1),
    (2, "Aguardando cliente", "waiting", 2),
    (3, "Concluído", "closed", 5),
    (4, "Cancelado", "canceled", 6),
    (6, "Entregue", "delivered", 3),
]
RESOLUTION_CODES = [
    "Feito",
    "Feito com solução de contorno",
    "Não reproduzível",
    "Fora do escopo do grupo",
]
TICKET_SEARCH = (
    "setweight(to_tsvector('pt_br'::regconfig, title), 'A') || "
    "setweight(to_tsvector('pt_br'::regconfig, description), 'B')"
)
COMMENT_SEARCH = "to_tsvector('pt_br'::regconfig, body)"


def _id(tipo: type[sa.types.TypeEngine[int]]) -> sa.Column[int]:
    return sa.Column("id", tipo(), sa.Identity(always=True), nullable=False)


def _public_id() -> sa.Column[str]:
    return sa.Column(
        "public_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
    )


def _agora(nome: str) -> sa.Column[object]:
    return sa.Column(
        nome, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _data(nome: str) -> sa.Column[object]:
    return sa.Column(nome, sa.DateTime(timezone=True), nullable=True)


def upgrade() -> None:
    # Extensões "trusted": o dono do banco cria sem superusuário (docs/18 §18.3, passo 3).
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    # Português + remoção de acentos. Com regconfig explícito, to_tsvector é IMMUTABLE
    # e pode ser usado em colunas geradas.
    op.execute("CREATE TEXT SEARCH CONFIGURATION pt_br (COPY = portuguese)")
    op.execute(
        "ALTER TEXT SEARCH CONFIGURATION pt_br "
        "ALTER MAPPING FOR hword, hword_part, word WITH unaccent, portuguese_stem"
    )

    op.create_table(
        "clients",
        _id(sa.BigInteger),
        _public_id(),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("trade_name", sa.Text(), nullable=True),
        sa.Column("document", sa.Text(), nullable=True),
        sa.Column("id_number", sa.Text(), nullable=True),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("state_registration", sa.Text(), nullable=True),
        sa.Column("municipal_registration", sa.Text(), nullable=True),
        sa.Column("contact_name", sa.Text(), nullable=True),
        sa.Column("postal_code", sa.Text(), nullable=False),
        sa.Column("street", sa.Text(), nullable=True),
        sa.Column("number", sa.Text(), nullable=True),
        sa.Column("complement", sa.Text(), nullable=True),
        sa.Column("district", sa.Text(), nullable=True),
        sa.Column("city", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        _agora("created_at"),
        _agora("updated_at"),
        sa.Column(
            "emails", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column(
            "phones", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("contract_type", sa.Text(), nullable=True),
        sa.Column("contract_hours", sa.Integer(), nullable=True),
        sa.CheckConstraint("kind IN ('person', 'company')", name=op.f("clients_kind_check")),
        sa.CheckConstraint("length(state) = 2", name=op.f("clients_state_check")),
        sa.CheckConstraint(
            "contract_type IN ('monthly', 'annual', 'on_demand')",
            name=op.f("clients_contract_type_check"),
        ),
        sa.CheckConstraint(
            "contract_hours IS NULL OR "
            "(contract_type IN ('monthly', 'annual') AND contract_hours > 0)",
            name=op.f("clients_contract_hours_check"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("clients_pkey")),
        sa.UniqueConstraint("document", name=op.f("clients_document_key")),
        sa.UniqueConstraint("public_id", name=op.f("clients_public_id_key")),
    )
    op.create_index("clients_name_idx", "clients", [sa.text("lower(name)")])

    op.create_table(
        "idempotency_keys",
        _id(sa.BigInteger),
        sa.Column("owner_hash", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("status_code", sa.SmallInteger(), nullable=True),
        sa.Column("headers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("body", postgresql.BYTEA(), nullable=True),
        _agora("created_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("idempotency_keys_pkey")),
        sa.UniqueConstraint("owner_hash", "key", name=op.f("idempotency_keys_owner_hash_key_key")),
    )

    # Fila de tarefas e outbox (eventos de domínio), consumidos pelo worker.
    op.create_table(
        "jobs",
        _id(sa.BigInteger),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column(
            "args",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default="queued", nullable=False),
        sa.Column("attempts", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.SmallInteger(), server_default="5", nullable=False),
        _agora("run_after"),
        sa.Column("dedup_key", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        _agora("created_at"),
        _data("finished_at"),
        sa.CheckConstraint(
            "status IN ('queued', 'done', 'failed')", name=op.f("jobs_status_check")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("jobs_pkey")),
        sa.UniqueConstraint("dedup_key", name=op.f("jobs_dedup_key_key")),
    )
    op.create_index(
        "jobs_ready_idx", "jobs", ["run_after"], postgresql_where=sa.text("status = 'queued'")
    )
    op.create_table(
        "outbox",
        _id(sa.BigInteger),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _agora("created_at"),
        _data("processed_at"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("outbox_pkey")),
    )
    op.create_index(
        "outbox_pending_idx", "outbox", ["id"], postgresql_where=sa.text("processed_at IS NULL")
    )

    op.create_table(
        "resolution_codes",
        _id(sa.SmallInteger),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("resolution_codes_pkey")),
        sa.UniqueConstraint("name", name=op.f("resolution_codes_name_key")),
    )
    op.create_table(
        "roles",
        _id(sa.SmallInteger),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("permissions", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        _agora("created_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("roles_pkey")),
        sa.UniqueConstraint("code", name=op.f("roles_code_key")),
    )
    op.create_table(
        "teams",
        _id(sa.BigInteger),
        _public_id(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "notify_on_new", sa.Text(), server_default=sa.text("'queue_only'"), nullable=False
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        _agora("created_at"),
        sa.CheckConstraint(
            "notify_on_new IN ('queue_only', 'email_all_members')",
            name=op.f("teams_notify_on_new_check"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("teams_pkey")),
        sa.UniqueConstraint("name", name=op.f("teams_name_key")),
        sa.UniqueConstraint("public_id", name=op.f("teams_public_id_key")),
    )
    op.create_table(
        "ticket_statuses",
        _id(sa.SmallInteger),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "is_default_for_kind", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('approval', 'open', 'waiting', 'delivered', 'closed', 'canceled')",
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
    op.create_table(
        "categories",
        _id(sa.BigInteger),
        _public_id(),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("default_team_id", sa.BigInteger(), nullable=True),
        sa.Column("default_type", sa.Text(), server_default=sa.text("'incident'"), nullable=False),
        sa.Column("is_confidential", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        _agora("created_at"),
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

    op.create_table(
        "users",
        _id(sa.BigInteger),
        _public_id(),
        sa.Column("email", postgresql.CITEXT(), nullable=True),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("role_id", sa.SmallInteger(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        _data("password_changed_at"),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        _data("last_login_at"),
        _agora("created_at"),
        _agora("updated_at"),
        sa.Column("username", postgresql.CITEXT(), nullable=True),
        sa.Column(
            "must_change_password", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("locale", sa.Text(), nullable=True),
        _data("deleted_at"),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=True),
        # O excluído fica sem e-mail e sem nome de usuário.
        sa.CheckConstraint(
            "deleted_at IS NOT NULL OR email IS NOT NULL OR username IS NOT NULL",
            name=op.f("users_login_check"),
        ),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], name=op.f("users_client_id_fkey")),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], name=op.f("users_role_id_fkey")),
        sa.PrimaryKeyConstraint("id", name=op.f("users_pkey")),
        sa.UniqueConstraint("email", name=op.f("users_email_key")),
        sa.UniqueConstraint("public_id", name=op.f("users_public_id_key")),
        sa.UniqueConstraint("username", name=op.f("users_username_key")),
    )
    op.create_index(op.f("users_client_id_idx"), "users", ["client_id"])

    op.create_table(
        "api_tokens",
        _id(sa.BigInteger),
        _public_id(),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        _agora("created_at"),
        _data("expires_at"),
        _data("last_used_at"),
        _data("revoked_at"),
        sa.CheckConstraint("scope IN ('read', 'write')", name=op.f("api_tokens_scope_check")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("api_tokens_user_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("api_tokens_pkey")),
        sa.UniqueConstraint("public_id", name=op.f("api_tokens_public_id_key")),
        sa.UniqueConstraint("token_hash", name=op.f("api_tokens_token_hash_key")),
    )
    op.create_index(op.f("api_tokens_user_id_idx"), "api_tokens", ["user_id"])
    op.create_table(
        "audit_log",
        _id(sa.BigInteger),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("target_type", sa.Text(), nullable=True),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        _agora("created_at"),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], name=op.f("audit_log_actor_user_id_fkey")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("audit_log_pkey")),
    )
    op.create_index(op.f("audit_log_created_at_idx"), "audit_log", ["created_at"])
    op.create_index("audit_log_target_idx", "audit_log", ["target_type", "target_id"])
    op.create_table(
        "auth_tokens",
        _id(sa.BigInteger),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _data("used_at"),
        _agora("created_at"),
        sa.CheckConstraint(
            "purpose IN ('invite', 'password_reset')", name=op.f("auth_tokens_purpose_check")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("auth_tokens_user_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("auth_tokens_pkey")),
        sa.UniqueConstraint("token_hash", name=op.f("auth_tokens_token_hash_key")),
    )
    op.create_index(op.f("auth_tokens_user_id_idx"), "auth_tokens", ["user_id"])
    # UNLOGGED: o limite de login por conta e IP vale com vários workers, sem pesar no WAL.
    op.create_table(
        "login_ip_failures",
        _id(sa.BigInteger),
        sa.Column("ip", sa.Text(), nullable=False),
        _agora("at"),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("login_ip_failures_user_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("login_ip_failures_pkey")),
        prefixes=["UNLOGGED"],
    )
    op.create_index("login_ip_failures_ip_idx", "login_ip_failures", ["ip", "at"])
    op.create_index("login_ip_failures_user_id_idx", "login_ip_failures", ["user_id", "ip", "at"])
    op.create_table(
        "report_exports",
        _id(sa.BigInteger),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("query", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _agora("created_at"),
        sa.CheckConstraint(
            "kind IN ('simple', 'detailed')", name=op.f("report_exports_kind_check")
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["clients.id"], name=op.f("report_exports_client_id_fkey")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("report_exports_user_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("report_exports_pkey")),
    )
    op.create_index(
        "report_exports_user_id_created_at_idx", "report_exports", ["user_id", "created_at"]
    )
    op.create_table(
        "settings",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        _agora("updated_at"),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name=op.f("settings_updated_by_fkey")
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("settings_pkey")),
    )
    op.create_table(
        "team_members",
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.Text(), server_default=sa.text("'member'"), nullable=False),
        sa.Column("source", sa.Text(), server_default=sa.text("'manual'"), nullable=False),
        _agora("added_at"),
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
    op.create_index(op.f("team_members_user_id_idx"), "team_members", ["user_id"])
    op.create_table(
        "user_sessions",
        _id(sa.BigInteger),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("csrf_token_hash", sa.Text(), nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        _agora("created_at"),
        _agora("last_seen_at"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _data("revoked_at"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("user_sessions_user_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("user_sessions_pkey")),
        sa.UniqueConstraint("token_hash", name=op.f("user_sessions_token_hash_key")),
    )
    op.create_index(op.f("user_sessions_user_id_idx"), "user_sessions", ["user_id"])
    # Vigências do expediente: da instalação (sem dono), de um grupo ou de uma pessoa.
    op.create_table(
        "work_schedules",
        _id(sa.BigInteger),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("team_id", sa.BigInteger(), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("weekdays", sa.ARRAY(sa.SmallInteger()), nullable=True),
        sa.Column("start", sa.Time(), nullable=True),
        sa.Column("end", sa.Time(), nullable=True),
        _agora("created_at"),
        sa.Column("break_start", sa.Time(), nullable=True),
        sa.Column("break_end", sa.Time(), nullable=True),
        sa.CheckConstraint(
            "weekdays <@ '{0,1,2,3,4,5,6}'::smallint[]",
            name=op.f("work_schedules_weekdays_check"),
        ),
        sa.CheckConstraint('"end" > start', name=op.f("work_schedules_range_check")),
        sa.CheckConstraint(
            '(weekdays IS NULL) = (start IS NULL) AND (start IS NULL) = ("end" IS NULL)',
            name=op.f("work_schedules_hours_check"),
        ),
        sa.CheckConstraint(
            "user_id IS NULL OR team_id IS NULL", name=op.f("work_schedules_owner_check")
        ),
        sa.CheckConstraint(
            "weekdays IS NOT NULL OR user_id IS NOT NULL OR team_id IS NOT NULL",
            name=op.f("work_schedules_installation_check"),
        ),
        sa.CheckConstraint(
            "(break_start IS NULL) = (break_end IS NULL) AND (break_start IS NULL OR "
            '(start < break_start AND break_start < break_end AND break_end < "end"))',
            name=op.f("work_schedules_break_check"),
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], name=op.f("work_schedules_team_id_fkey"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("work_schedules_user_id_fkey"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("work_schedules_pkey")),
        sa.UniqueConstraint(
            "user_id",
            "team_id",
            "valid_from",
            name=op.f("work_schedules_user_id_team_id_valid_from_key"),
            postgresql_nulls_not_distinct=True,
        ),
    )

    # Número legível do chamado (#1234), nunca reutilizado.
    op.execute("CREATE SEQUENCE ticket_number_seq START WITH 1000")
    op.create_table(
        "tickets",
        _id(sa.BigInteger),
        _public_id(),
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
        sa.Column("beneficiary_name", sa.Text(), nullable=True),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("assignee_id", sa.BigInteger(), nullable=False),
        sa.Column("category_id", sa.BigInteger(), nullable=True),
        sa.Column("status_id", sa.SmallInteger(), nullable=False),
        sa.Column("resolution_code_id", sa.SmallInteger(), nullable=True),
        sa.Column("reopened_count", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        _agora("created_at"),
        _agora("updated_at"),
        _data("first_assigned_at"),
        _data("closed_at"),
        _agora("started_at"),
        sa.Column("client_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(TICKET_SEARCH, persisted=True),
            nullable=True,
        ),
        _data("canceled_at"),
        sa.CheckConstraint(
            "type IN ('incident', 'request', 'task')", name=op.f("tickets_type_check")
        ),
        sa.CheckConstraint("length(title) BETWEEN 3 AND 300", name=op.f("tickets_title_check")),
        sa.ForeignKeyConstraint(
            ["assignee_id"], ["users.id"], name=op.f("tickets_assignee_id_fkey")
        ),
        sa.ForeignKeyConstraint(
            ["category_id"], ["categories.id"], name=op.f("tickets_category_id_fkey")
        ),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], name=op.f("tickets_client_id_fkey")),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], name=op.f("tickets_created_by_id_fkey")
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
    op.create_index("tickets_assignee_idx", "tickets", ["assignee_id", "status_id"])
    op.create_index("tickets_client_idx", "tickets", ["client_id"])
    op.create_index("tickets_created_idx", "tickets", ["created_at", "id"])
    op.create_index("tickets_queue_idx", "tickets", ["team_id", "status_id", "created_at"])
    op.create_index("tickets_search_idx", "tickets", ["search_vector"], postgresql_using="gin")

    op.create_table(
        "ticket_co_assignees",
        sa.Column("ticket_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        _agora("added_at"),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            name=op.f("ticket_co_assignees_ticket_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("ticket_co_assignees_user_id_fkey")
        ),
        sa.PrimaryKeyConstraint("ticket_id", "user_id", name=op.f("ticket_co_assignees_pkey")),
    )
    op.create_index(op.f("ticket_co_assignees_user_id_idx"), "ticket_co_assignees", ["user_id"])
    op.create_table(
        "ticket_comments",
        _id(sa.BigInteger),
        _public_id(),
        sa.Column("ticket_id", sa.BigInteger(), nullable=False),
        sa.Column("author_id", sa.BigInteger(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_solution", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        _agora("created_at"),
        _data("edited_at"),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(COMMENT_SEARCH, persisted=True),
            nullable=True,
        ),
        sa.Column("time_spent_minutes", sa.Integer(), nullable=True),
        _agora("done_at"),
        _data("deleted_at"),
        sa.CheckConstraint("length(body) > 0", name=op.f("ticket_comments_body_check")),
        sa.CheckConstraint(
            "time_spent_minutes > 0", name=op.f("ticket_comments_time_spent_minutes_check")
        ),
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
        "ticket_comments_done_idx",
        "ticket_comments",
        ["done_at"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ticket_comments_search_idx", "ticket_comments", ["search_vector"], postgresql_using="gin"
    )
    op.create_index("ticket_comments_ticket_idx", "ticket_comments", ["ticket_id", "created_at"])
    op.create_table(
        "ticket_events",
        _id(sa.BigInteger),
        sa.Column("ticket_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        _agora("created_at"),
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
    op.create_index("ticket_events_ticket_idx", "ticket_events", ["ticket_id", "created_at"])
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
    # UNLOGGED: a presença no chamado vale com vários workers, sem pesar no WAL.
    op.create_table(
        "ticket_presence",
        sa.Column("ticket_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        _agora("seen_at"),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.public_id"],
            name=op.f("ticket_presence_ticket_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("ticket_presence_user_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("ticket_id", "user_id", name=op.f("ticket_presence_pkey")),
        prefixes=["UNLOGGED"],
    )
    op.create_table(
        "ticket_reads",
        sa.Column("ticket_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        _agora("read_at"),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            name=op.f("ticket_reads_ticket_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("ticket_reads_user_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("ticket_id", "user_id", name=op.f("ticket_reads_pkey")),
    )
    op.create_table(
        "ticket_teams",
        sa.Column("ticket_id", sa.BigInteger(), nullable=False),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        _agora("first_at"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], name=op.f("ticket_teams_team_id_fkey")),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            name=op.f("ticket_teams_ticket_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("ticket_id", "team_id", name=op.f("ticket_teams_pkey")),
    )
    op.create_index(op.f("ticket_teams_team_id_idx"), "ticket_teams", ["team_id"])
    op.create_table(
        "ticket_watchers",
        sa.Column("ticket_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), server_default=sa.text("'watcher'"), nullable=False),
        sa.Column("added_by", sa.BigInteger(), nullable=True),
        _agora("added_at"),
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
    op.create_index(op.f("ticket_watchers_user_id_idx"), "ticket_watchers", ["user_id"])
    op.create_table(
        "attachments",
        _id(sa.BigInteger),
        _public_id(),
        sa.Column("ticket_id", sa.BigInteger(), nullable=True),
        sa.Column("comment_id", sa.BigInteger(), nullable=True),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("uploaded_by", sa.BigInteger(), nullable=False),
        _agora("created_at"),
        _data("linked_at"),
        sa.CheckConstraint("size_bytes > 0", name=op.f("attachments_size_bytes_check")),
        sa.CheckConstraint(
            "comment_id IS NULL OR ticket_id IS NOT NULL",
            name=op.f("attachments_comment_needs_ticket_check"),
        ),
        sa.CheckConstraint(
            "(linked_at IS NULL) = (ticket_id IS NULL)", name=op.f("attachments_linked_check")
        ),
        sa.ForeignKeyConstraint(
            ["comment_id"],
            ["ticket_comments.id"],
            name=op.f("attachments_comment_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            name=op.f("attachments_ticket_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"], ["users.id"], name=op.f("attachments_uploaded_by_fkey")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("attachments_pkey")),
        sa.UniqueConstraint("public_id", name=op.f("attachments_public_id_key")),
        sa.UniqueConstraint("storage_key", name=op.f("attachments_storage_key_key")),
    )
    op.create_index(
        "attachments_ticket_idx",
        "attachments",
        ["ticket_id"],
        postgresql_where=sa.text("ticket_id IS NOT NULL"),
    )
    op.create_index(
        "attachments_orphans_idx",
        "attachments",
        ["created_at"],
        postgresql_where=sa.text("linked_at IS NULL"),
    )

    _dados_iniciais()


def _dados_iniciais() -> None:
    op.bulk_insert(
        sa.table(
            "roles",
            sa.column("code", sa.Text),
            sa.column("name", sa.Text),
            sa.column("permissions", sa.ARRAY(sa.Text)),
            sa.column("is_system", sa.Boolean),
        ),
        [
            {"code": code, "name": name, "permissions": perms, "is_system": True}
            for code, name, perms in SYSTEM_ROLES
        ],
    )
    op.bulk_insert(
        sa.table("resolution_codes", sa.column("name", sa.Text)),
        [{"name": name} for name in RESOLUTION_CODES],
    )
    for id_, name, kind, order in STATUSES:
        op.execute(
            sa.text(
                "INSERT INTO ticket_statuses (id, name, kind, sort_order, is_default_for_kind) "
                "OVERRIDING SYSTEM VALUE VALUES (:id, :name, :kind, :order, true)"
            ).bindparams(id=id_, name=name, kind=kind, order=order)
        )
    op.execute("SELECT setval('ticket_statuses_id_seq', (SELECT max(id) FROM ticket_statuses))")

    # Administrador padrão (docs/09 §9.2): entra com admin/admin e troca a senha na hora. Todo
    # usuário é membro de pelo menos um grupo (docs/08 §8.1): ele fica no grupo Administradores.
    op.execute(
        sa.text(
            """
            INSERT INTO users
                (username, full_name, display_name, role_id, password_hash, must_change_password)
            SELECT 'admin', 'Administrador', 'Administrador', r.id, :hash, true
            FROM roles r WHERE r.code = 'admin'
            """
        ).bindparams(hash=PasswordHasher().hash("admin"))
    )
    op.execute(
        "INSERT INTO teams (name, description) "
        "VALUES ('Administradores', 'Responsáveis pelo sistema')"
    )
    op.execute(
        "INSERT INTO team_members (team_id, user_id) "
        "SELECT t.id, u.id FROM teams t, users u "
        "WHERE t.name = 'Administradores' AND u.username = 'admin'"
    )
    # Expediente da instalação, desde sempre: segunda a sexta, das 8h às 18h.
    op.execute(
        'INSERT INTO work_schedules (weekdays, start, "end") '
        "VALUES ('{0,1,2,3,4}', '08:00', '18:00')"
    )


def downgrade() -> None:
    for tabela in (
        "attachments",
        "ticket_watchers",
        "ticket_teams",
        "ticket_reads",
        "ticket_presence",
        "ticket_events",
        "ticket_comments",
        "ticket_co_assignees",
        "tickets",  # leva junto a ticket_number_seq (OWNED BY)
        "work_schedules",
        "user_sessions",
        "team_members",
        "settings",
        "report_exports",
        "login_ip_failures",
        "auth_tokens",
        "audit_log",
        "api_tokens",
        "users",
        "categories",
        "ticket_statuses",
        "teams",
        "roles",
        "resolution_codes",
        "outbox",
        "jobs",
        "idempotency_keys",
        "clients",
    ):
        op.drop_table(tabela)  # leva junto os índices e a trigger
    op.execute("DROP FUNCTION ticket_events_append_only()")
    op.execute("DROP TEXT SEARCH CONFIGURATION pt_br")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
    op.execute("DROP EXTENSION IF EXISTS unaccent")
    op.execute("DROP EXTENSION IF EXISTS citext")
