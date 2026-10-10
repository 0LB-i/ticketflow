"""Importa todos os modelos, para o Alembic e para os relacionamentos por nome."""

from chamados.modules.audit.models import AuditLog
from chamados.modules.catalog.models import Category, ResolutionCode, TicketStatus
from chamados.modules.identity.models import AuthToken, User, UserSession
from chamados.modules.organization.models import Department, Role, Team, TeamMember
from chamados.modules.system.models import SystemSetting
from chamados.modules.tickets.models import (
    Ticket,
    TicketComment,
    TicketEvent,
    TicketTeam,
    TicketWatcher,
)

__all__ = [
    "AuditLog",
    "AuthToken",
    "Category",
    "Department",
    "ResolutionCode",
    "Role",
    "SystemSetting",
    "Team",
    "TeamMember",
    "Ticket",
    "TicketComment",
    "TicketEvent",
    "TicketStatus",
    "TicketTeam",
    "TicketWatcher",
    "User",
    "UserSession",
]
