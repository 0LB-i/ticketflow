"""Catálogo de permissões e papéis do sistema (docs/08 §8.3).

As permissões são códigos fixos. Um papel é uma lista deles. Algumas só valem para quem é
supervisor do grupo em questão (👤 na matriz do docs/08): o papel Agente não as tem
globalmente, e `can()` as concede pela supervisão.

O filtro de visibilidade de chamados (`ticket_visibility_filter`) fica em
modules/tickets/visibility.py, e as ações em um chamado, em modules/tickets/rules.py.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum


class P(StrEnum):
    TICKET_CREATE = "ticket.create"
    TICKET_VIEW_TEAM = "ticket.view_team"
    TICKET_VIEW_ALL = "ticket.view_all"
    TICKET_COMMENT = "ticket.comment"
    TICKET_EDIT = "ticket.edit"
    TICKET_SET_PRIORITY = "ticket.set_priority"
    TICKET_ASSIGN_SELF = "ticket.assign_self"
    TICKET_ASSIGN_OTHERS = "ticket.assign_others"
    TICKET_TRANSFER = "ticket.transfer"
    TICKET_TRANSITION = "ticket.transition"
    TICKET_APPROVE = "ticket.approve"
    TICKET_WATCH = "ticket.watch"
    TICKET_MERGE = "ticket.merge"
    TICKET_BULK = "ticket.bulk"
    TICKET_HIDE_CONTENT = "ticket.hide_content"
    TICKET_EXPORT = "ticket.export"
    KB_READ = "kb.read"
    KB_WRITE = "kb.write"
    KB_PUBLISH = "kb.publish"
    REPORT_VIEW_TEAM = "report.view_team"
    REPORT_VIEW_ALL = "report.view_all"
    ADMIN_USERS = "admin.users"
    ADMIN_ORGANIZATION = "admin.organization"
    ADMIN_CATALOG = "admin.catalog"
    ADMIN_SETTINGS = "admin.settings"
    AUDIT_VIEW = "audit.view"
    CLIENT_VIEW = "client.view"
    CLIENT_MANAGE = "client.manage"


# Concedidas a quem é supervisor do grupo do chamado (👤).
SUPERVISOR = frozenset(
    {
        P.TICKET_APPROVE,
        P.TICKET_BULK,
        P.TICKET_HIDE_CONTENT,
        P.TICKET_EXPORT,
        P.KB_PUBLISH,
        P.REPORT_VIEW_TEAM,
    }
)

ROLES: dict[str, frozenset[P]] = {
    "agent": frozenset(
        {
            P.TICKET_CREATE,
            P.TICKET_VIEW_TEAM,
            P.TICKET_COMMENT,
            P.TICKET_EDIT,
            P.TICKET_SET_PRIORITY,
            P.TICKET_ASSIGN_SELF,
            P.TICKET_ASSIGN_OTHERS,
            P.TICKET_TRANSFER,
            P.TICKET_TRANSITION,
            P.TICKET_WATCH,
            P.TICKET_MERGE,
            P.KB_READ,
            P.KB_WRITE,
            P.CLIENT_VIEW,
            P.CLIENT_MANAGE,
        }
    ),
    "admin": frozenset(P),
    "auditor": frozenset(
        {
            P.TICKET_VIEW_TEAM,
            P.TICKET_VIEW_ALL,
            P.TICKET_EXPORT,
            P.KB_READ,
            P.REPORT_VIEW_TEAM,
            P.REPORT_VIEW_ALL,
            P.AUDIT_VIEW,
            P.CLIENT_VIEW,
        }
    ),
}

ROLE_NAMES = {"agent": "Agente", "admin": "Administrador", "auditor": "Auditor"}


@dataclass(frozen=True)
class Actor:
    """Quem está agindo, com o que importa para decidir permissões."""

    user_id: int
    role: str
    teams: frozenset[int] = field(default_factory=frozenset)
    supervises: frozenset[int] = field(default_factory=frozenset)

    @property
    def permissions(self) -> frozenset[P]:
        return ROLES.get(self.role, frozenset())


def can(actor: Actor, permission: P, team_id: int | None = None) -> bool:
    """O ator tem a permissão (no grupo indicado, quando ela depende do grupo)?"""
    if permission in actor.permissions:
        return True
    return permission in SUPERVISOR and team_id is not None and team_id in actor.supervises


def effective_permissions(actor: Actor) -> list[str]:
    """Permissões globais + as de supervisor, se supervisionar algum grupo (para a interface)."""
    perms: Iterable[P] = actor.permissions | (SUPERVISOR if actor.supervises else frozenset())
    return sorted(perms)
