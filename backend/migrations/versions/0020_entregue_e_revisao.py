""" "Entregue" passa a ser o status de revisão do supervisor (decisão de 2026-10-14).

O "Entregue" de conclusão sai (os chamados nele vão para o padrão dos concluídos, "Concluído") e
o status de revisão ("Em espera de revisão") passa a se chamar "Entregue". Onde isso já foi feito
pelas Configurações, nada muda.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENTREGUE_CONCLUSAO = "name = 'Entregue' AND kind = 'closed' AND NOT is_default_for_kind"
HA_REVISAO = "EXISTS (SELECT 1 FROM ticket_statuses WHERE is_review)"


def upgrade() -> None:
    op.execute(
        "UPDATE tickets SET status_id = (SELECT id FROM ticket_statuses "
        "WHERE kind = 'closed' AND is_default_for_kind) "
        f"WHERE status_id IN (SELECT id FROM ticket_statuses WHERE {ENTREGUE_CONCLUSAO}) "
        f"AND {HA_REVISAO}"
    )
    op.execute(f"DELETE FROM ticket_statuses WHERE {ENTREGUE_CONCLUSAO} AND {HA_REVISAO}")
    op.execute(
        "UPDATE ticket_statuses SET name = 'Entregue' "
        "WHERE is_review AND name = 'Em espera de revisão' "
        "AND NOT EXISTS (SELECT 1 FROM ticket_statuses WHERE name = 'Entregue')"
    )


def downgrade() -> None:
    # O nome volta; o "Entregue" de conclusão é recriado, logo antes do padrão dos concluídos.
    # Os chamados que foram para "Concluído" ficam lá.
    op.execute(
        "UPDATE ticket_statuses SET name = 'Em espera de revisão' "
        "WHERE is_review AND name = 'Entregue' "
        "AND NOT EXISTS (SELECT 1 FROM ticket_statuses WHERE name = 'Em espera de revisão')"
    )
    op.execute(
        """
        WITH antes AS (
            SELECT sort_order AS ordem FROM ticket_statuses
            WHERE kind = 'closed' AND is_default_for_kind
        ), abre AS (
            UPDATE ticket_statuses SET sort_order = sort_order + 1
            WHERE sort_order >= (SELECT ordem FROM antes)
        )
        INSERT INTO ticket_statuses (name, kind, sort_order, is_default_for_kind)
        SELECT 'Entregue', 'closed', ordem, false FROM antes
        ON CONFLICT (name) DO NOTHING
        """
    )
