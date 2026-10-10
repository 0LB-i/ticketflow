"""Consulta do log de auditoria (docs/13: /admin/auditoria). Exige audit.view."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select

from chamados.core.permissions import P
from chamados.db.session import DB
from chamados.modules.audit.models import AuditLog
from chamados.modules.identity.deps import Auth, require
from chamados.modules.identity.models import User

router = APIRouter(prefix="/admin/audit-log", tags=["auditoria"])


class AuditEntry(BaseModel):
    id: int
    action: str
    actor_id: uuid.UUID | None
    actor_name: str | None
    target_type: str | None
    target_id: str | None
    ip: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    created_at: datetime


class AuditPage(BaseModel):
    items: list[AuditEntry]
    next_cursor: int | None


@router.get("", response_model=AuditPage)
async def list_audit(
    _: Annotated[Auth, Depends(require(P.AUDIT_VIEW))],
    db: DB,
    action: str | None = Query(default=None, description="prefixo, ex.: auth. ou user."),
    cursor: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> AuditPage:
    stmt = (
        select(AuditLog, User)
        .outerjoin(User, User.id == AuditLog.actor_user_id)
        .order_by(AuditLog.id.desc())
        .limit(limit + 1)
    )
    if action:
        stmt = stmt.where(AuditLog.action.startswith(action))
    if cursor:
        stmt = stmt.where(AuditLog.id < cursor)
    rows = (await db.execute(stmt)).all()
    items = [
        AuditEntry(
            id=log.id,
            action=log.action,
            actor_id=user.public_id if user else None,
            actor_name=user.full_name if user else None,
            target_type=log.target_type,
            target_id=log.target_id,
            ip=str(log.ip) if log.ip else None,
            before=log.before,
            after=log.after,
            created_at=log.created_at,
        )
        for log, user in rows[:limit]
    ]
    return AuditPage(items=items, next_cursor=items[-1].id if len(rows) > limit else None)
