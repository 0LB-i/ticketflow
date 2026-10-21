"""Tarefa do worker que envia um e-mail já montado pelo handler (handlers.py)."""

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from chamados.config import Settings
from chamados.modules.notifications.email import make_mailer


async def send_email(_db: AsyncSession, settings: Settings, args: dict[str, Any]) -> None:
    """Uma falha do SMTP sobe: a fila tenta de novo (jobs.service.run_next)."""
    mailer = make_mailer(settings)
    await asyncio.to_thread(mailer.deliver, args["to"], args["subject"], args["body"])
