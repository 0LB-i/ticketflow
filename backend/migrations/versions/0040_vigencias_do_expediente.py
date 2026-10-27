"""`work_schedules`: as vigências do expediente da instalação, de cada grupo e de cada pessoa
(docs/14 §14.7). O expediente que estava na chave `work_hours` de `settings` vira a vigência da
instalação desde sempre; a chave fica só com os feriados, que continuam valendo para todos.

Revision ID: 0040
Revises: 0039
Create Date: 2026-10-27
"""

import json
from collections.abc import Sequence
from datetime import time

import sqlalchemy as sa
from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# O padrão de `work_hours.DEFAULT_SCHEDULE`, copiado: a migração não importa o código do app.
DEFAULT = {"weekdays": [0, 1, 2, 3, 4], "start": "08:00:00", "end": "18:00:00"}


def upgrade() -> None:
    op.create_table(
        "work_schedules",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("team_id", sa.BigInteger(), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("weekdays", sa.ARRAY(sa.SmallInteger()), nullable=True),
        sa.Column("start", sa.Time(), nullable=True),
        sa.Column("end", sa.Time(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name=op.f("work_schedules_team_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("work_schedules_user_id_fkey"),
            ondelete="RESTRICT",
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

    # Carga inicial (o autogenerate não a vê): o expediente de hoje, desde sempre.
    bind = op.get_bind()
    saved = bind.execute(sa.text("SELECT value FROM settings WHERE key = 'work_hours'")).scalar()
    hours = saved or DEFAULT
    bind.execute(
        sa.text(
            'INSERT INTO work_schedules (weekdays, start, "end") '
            "VALUES (CAST(:weekdays AS smallint[]), :start, :end)"
        ),
        {
            "weekdays": hours["weekdays"],
            "start": time.fromisoformat(hours["start"]),
            "end": time.fromisoformat(hours["end"]),
        },
    )
    bind.execute(
        sa.text(
            "UPDATE settings SET value = jsonb_build_object('holidays', "
            "coalesce(value->'holidays', '[]'::jsonb)) WHERE key = 'work_hours'"
        )
    )


def downgrade() -> None:
    # A chave volta a ter o expediente: o da instalação que vale hoje, com os feriados.
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            'SELECT weekdays, start, "end" FROM work_schedules '
            "WHERE user_id IS NULL AND team_id IS NULL "
            "AND (valid_from IS NULL OR valid_from <= current_date) "
            "ORDER BY valid_from DESC NULLS LAST LIMIT 1"
        )
    ).first()
    hours = (
        {"weekdays": list(row[0]), "start": row[1].isoformat(), "end": row[2].isoformat()}
        if row
        else DEFAULT
    )
    saved = bind.execute(sa.text("SELECT value FROM settings WHERE key = 'work_hours'")).scalar()
    value = json.dumps({**hours, "holidays": (saved or {}).get("holidays", [])})
    bind.execute(
        sa.text(
            "INSERT INTO settings (key, value) VALUES ('work_hours', CAST(:value AS jsonb)) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        ),
        {"value": value},
    )
    op.drop_table("work_schedules")
