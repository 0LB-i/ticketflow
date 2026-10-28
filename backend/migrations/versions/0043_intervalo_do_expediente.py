"""`work_schedules.break_start`/`break_end`: o intervalo do expediente (opcional, dentro do
horário). As vigências que já existem ficam sem intervalo: a hora extra dos dias de antes não
muda (docs/14 §14.7).

Revision ID: 0043
Revises: 0042
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("work_schedules", sa.Column("break_start", sa.Time(), nullable=True))
    op.add_column("work_schedules", sa.Column("break_end", sa.Time(), nullable=True))
    op.create_check_constraint(
        op.f("work_schedules_break_check"),
        "work_schedules",
        "(break_start IS NULL) = (break_end IS NULL) AND (break_start IS NULL OR "
        '(start < break_start AND break_start < break_end AND break_end < "end"))',
    )


def downgrade() -> None:
    op.drop_constraint(op.f("work_schedules_break_check"), "work_schedules", type_="check")
    op.drop_column("work_schedules", "break_end")
    op.drop_column("work_schedules", "break_start")
