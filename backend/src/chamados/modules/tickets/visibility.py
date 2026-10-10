"""Quem vê cada chamado (docs/08 §8.4).

`ticket_visibility_filter` é o único lugar que decide a visibilidade: toda leitura de chamados
(lista, detalhe, comentários, histórico e, depois, busca, relatórios e anexos) passa por ele.
"""

from sqlalchemy import ColumnElement, and_, exists, false, or_, true

from chamados.core.permissions import Actor, P, can
from chamados.modules.catalog.models import Category
from chamados.modules.tickets.models import Ticket, TicketTeam, TicketWatcher

# Regra 6: leem tudo, inclusive os confidenciais (o acesso a estes vai para a auditoria).
SEE_EVERYTHING = frozenset({"admin", "auditor"})


def ticket_visibility_filter(actor: Actor) -> ColumnElement[bool]:
    if actor.role in SEE_EVERYTHING:
        return true()
    not_confidential = ~exists().where(Category.id == Ticket.category_id, Category.is_confidential)
    rules: list[ColumnElement[bool]] = [
        Ticket.assignee_id == actor.user_id,  # 3
        exists().where(  # 4 (inclui os mencionados)
            TicketWatcher.ticket_id == Ticket.id, TicketWatcher.user_id == actor.user_id
        ),
    ]
    if can(actor, P.TICKET_VIEW_TEAM) and actor.teams:
        rules.append(Ticket.team_id.in_(actor.teams))  # 1
        rules.append(  # 2: grupos que atuaram antes de uma transferência
            and_(
                not_confidential,
                exists().where(
                    TicketTeam.ticket_id == Ticket.id, TicketTeam.team_id.in_(actor.teams)
                ),
            )
        )
    if can(actor, P.TICKET_VIEW_ALL):
        rules.append(not_confidential)  # 5
    return or_(false(), *rules)


def sees_without_privilege(actor: Actor, ticket: Ticket) -> bool:
    """Regras 1, 3 e 4: o acesso de admin/auditor fora delas a um confidencial é auditado."""
    return (
        ticket.team_id in actor.teams
        or ticket.assignee_id == actor.user_id
        or any(w.user_id == actor.user_id for w in ticket.watchers)
    )
