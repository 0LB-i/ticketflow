"""Leva o que chega da ponte do WhatsApp para o banco. Roda dentro do worker (`chamados worker`),
ao lado da fila de tarefas: pede os eventos à ponte (long-poll), grava numa transação e só então
confirma (`ack`), para a ponte apagar. Se o worker cair antes do commit, a ponte entrega de novo,
e o índice único das mensagens não deixa entrar duas vezes."""

import asyncio
from contextlib import suppress
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from chamados.config import Settings
from chamados.modules.whatsapp import service
from chamados.modules.whatsapp.bridge import Bridge, BridgeError, get_bridge

log = structlog.get_logger(__name__)

WAIT_S = 25  # o long-poll: a ponte responde assim que chega um evento
RETRY_S = 5  # ponte fora do ar: tenta de novo depois disto


async def drain(sessionmaker: async_sessionmaker[AsyncSession], bridge: Bridge, wait: int) -> int:
    """Um lote: grava os eventos pendentes e confirma. Devolve quantos foram gravados."""
    events = await bridge.events(wait)
    if not events:
        return 0
    async with sessionmaker() as db:
        await service.ingest(db, events)
    await bridge.ack(max(int(e["seq"]) for e in events))
    return len(events)


async def run(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings, stop: asyncio.Event
) -> None:
    bridge = get_bridge(settings)
    down = False
    while not stop.is_set():
        try:
            total = await _until_stop(drain(sessionmaker, bridge, WAIT_S), stop)
        except BridgeError:
            # Sem a ponte instalada ou fora do ar: avisa uma vez e continua tentando.
            if not down:
                log.warning("whatsapp_ponte_fora_do_ar")
                down = True
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), RETRY_S)
            continue
        if down:
            log.info("whatsapp_ponte_de_volta")
            down = False
        if total:
            log.info("whatsapp_eventos_gravados", total=total)


async def _until_stop(work: Any, stop: asyncio.Event) -> int:
    """O long-poll segura até 25 s: o SIGTERM não espera por ele."""
    task = asyncio.ensure_future(work)
    stopper = asyncio.ensure_future(stop.wait())
    done, _ = await asyncio.wait({task, stopper}, return_when=asyncio.FIRST_COMPLETED)
    if task in done:
        stopper.cancel()
        return int(task.result())
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    return 0
