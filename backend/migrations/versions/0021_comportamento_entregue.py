"""Comportamento próprio para "Entregue" (kind delivered), com ele como padrão; sai is_review.

Entregue: o trabalho foi entregue e espera a revisão do supervisor, que é quem conclui. Era um
status de espera marcado com is_review (0019/0020); passa a ser um comportamento, como os outros.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECK = "ticket_statuses_kind_check"


def _kinds(*kinds: str) -> None:
    op.drop_constraint(op.f(CHECK), "ticket_statuses", type_="check")
    op.create_check_constraint(op.f(CHECK), "ticket_statuses", f"kind IN {kinds}")


def upgrade() -> None:
    _kinds("approval", "open", "waiting", "delivered", "closed", "canceled")
    op.execute(
        "UPDATE ticket_statuses SET kind = 'delivered', is_default_for_kind = true WHERE is_review"
    )
    op.drop_column("ticket_statuses", "is_review")


def downgrade() -> None:
    op.add_column(
        "ticket_statuses",
        sa.Column("is_review", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    # Volta a ser um status de espera marcado como revisão; outros "delivered" criados depois
    # também viram espera.
    op.execute(
        "UPDATE ticket_statuses SET kind = 'waiting', is_default_for_kind = false, "
        "is_review = is_default_for_kind WHERE kind = 'delivered'"
    )
    _kinds("approval", "open", "waiting", "closed", "canceled")
