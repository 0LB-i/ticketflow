"""Importa todos os modelos, para o Alembic e para os relacionamentos por nome."""

from chamados.modules.audit.models import AuditLog
from chamados.modules.identity.models import AuthToken, User, UserSession
from chamados.modules.organization.models import Department, Role, Team, TeamMember

__all__ = [
    "AuditLog",
    "AuthToken",
    "Department",
    "Role",
    "Team",
    "TeamMember",
    "User",
    "UserSession",
]
