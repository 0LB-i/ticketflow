"""Registro na auditoria (docs/08 §8.8, docs/09 §9.8)."""

import ipaddress
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from chamados.modules.audit.models import AuditLog


def client_ip(request: Request | None) -> str | None:
    host = request.client.host if request and request.client else None
    try:
        return str(ipaddress.ip_address(host)) if host else None
    except ValueError:
        return None


def record(
    db: AsyncSession,
    action: str,
    *,
    request: Request | None = None,
    actor_user_id: int | None = None,
    target_type: str | None = None,
    target_id: object = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            action=action,
            actor_user_id=actor_user_id,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            ip=client_ip(request),
            user_agent=request.headers.get("user-agent") if request else None,
            before=before,
            after=after,
        )
    )
