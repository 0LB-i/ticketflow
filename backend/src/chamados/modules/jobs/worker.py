"""O processo `chamados worker` (ticketflow-worker.service): repassa o outbox, agenda as rotinas
e executa as tarefas da fila, uma por vez. SIGTERM ou SIGINT encerram depois da tarefa em curso.

Um erro de banco (PostgreSQL fora do ar) derruba o processo; o systemd o sobe de novo.
"""

import asyncio
import signal
from contextlib import suppress
from datetime import UTC, datetime, time
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from chamados.config import Settings
from chamados.db.engine import create_engine
from chamados.db.session import make_sessionmaker
from chamados.modules.attachments.service import purge
from chamados.modules.jobs import service

log = structlog.get_logger(__name__)

IDLE_SECONDS = 2  # espera quando não há nada a fazer


async def _purge_attachments(db: AsyncSession, settings: Settings, _args: dict[str, Any]) -> None:
    log.info("anexos_nao_vinculados_apagados", total=await purge(db, settings.files_dir))


TASKS: dict[str, service.Task] = {
    "attachments.purge": _purge_attachments,
    "jobs.cleanup": service.cleanup,
}
# Rotinas diárias (docs/10 §10.11), no horário de São Paulo.
ROUTINES = {"attachments.purge": time(3, 0), "jobs.cleanup": time(3, 30)}
# Eventos do outbox que viram tarefas; as notificações entram na F1-S4-04.
HANDLERS: dict[str, service.Handler] = {}


async def tick(sessionmaker: async_sessionmaker[AsyncSession], settings: Settings) -> bool:
    """Uma volta do loop. Devolve False se não havia nada a fazer."""
    async with sessionmaker() as db:
        relayed = await service.relay(db, HANDLERS)
    async with sessionmaker() as db:
        await service.schedule(db, ROUTINES, datetime.now(UTC))
    ran = await service.run_next(sessionmaker, settings, TASKS)
    return relayed > 0 or ran


async def run(settings: Settings, stop: asyncio.Event) -> None:
    engine = create_engine(settings.database_url)
    sessionmaker = make_sessionmaker(engine)
    log.info("worker_iniciado")
    try:
        while not stop.is_set():
            if not await tick(sessionmaker, settings):
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), IDLE_SECONDS)
    finally:
        await engine.dispose()
        log.info("worker_encerrado")


def main(settings: Settings) -> None:
    async def start() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        await run(settings, stop)

    asyncio.run(start())
