"""Importa todos os modelos, para o Alembic e para os relacionamentos por nome."""

from chamados.modules.attachments.models import Attachment
from chamados.modules.audit.models import AuditLog
from chamados.modules.catalog.models import Category, ResolutionCode, TicketStatus
from chamados.modules.clients.models import Client
from chamados.modules.identity.models import AuthToken, User, UserSession
from chamados.modules.jobs.models import Job, OutboxEvent
from chamados.modules.organization.models import Role, Team, TeamMember
from chamados.modules.reports.models import ReportModel
from chamados.modules.system.models import SystemSetting
from chamados.modules.tickets.models import (
    Ticket,
    TicketComment,
    TicketEvent,
    TicketTeam,
    TicketWatcher,
)

__all__ = [
    "Attachment",
    "AuditLog",
    "AuthToken",
    "Category",
    "Client",
    "Job",
    "OutboxEvent",
    "ReportModel",
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
