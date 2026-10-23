"""Outbox e fila de tarefas no PostgreSQL (ADR 0003): sem broker, transacional com os dados."""

from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from chamados.config import Settings
from chamados.modules.identity import idempotency
from chamados.modules.identity.models import IdempotencyKey
from chamados.modules.jobs.models import Job, OutboxEvent

log = structlog.get_logger(__name__)

TZ = ZoneInfo("America/Sao_Paulo")  # o horário das rotinas
KEEP_DONE = timedelta(days=7)  # tarefas concluídas e eventos processados
KEEP_FAILED = timedelta(days=30)  # tarefas que falharam de vez, para investigar

# Uma tarefa recebe a própria sessão (faz commit do seu trabalho), as configurações e os args.
Task = Callable[[AsyncSession, Settings, dict[str, Any]], Awaitable[None]]
# Um handler transforma um evento do outbox em tarefas (enqueue), na sessão do repasse.
Handler = Callable[[AsyncSession, Settings, OutboxEvent], Awaitable[None]]


def publish(db: AsyncSession, event_type: str, **payload: Any) -> None:
    """Grava o evento no outbox, na transação de quem chama: um rollback o desfaz junto."""
    db.add(OutboxEvent(event_type=event_type, payload=payload))


def enqueue(db: AsyncSession, task: str, **args: Any) -> None:
    db.add(Job(task=task, args=args))


async def relay(
    db: AsyncSession, settings: Settings, handlers: Mapping[str, Handler], limit: int = 100
) -> int:
    """Repassa um lote do outbox aos handlers e marca os eventos como processados, numa transação
    só: as tarefas e o `processed_at` entram juntos. Devolve quantos eventos foram repassados.

    Um handler que falha não trava os outros: o que ele fez é desfeito, o erro fica no evento e vai
    para o log. Evento sem handler só é marcado.
    """
    events = (
        await db.scalars(
            select(OutboxEvent)
            .where(OutboxEvent.processed_at.is_(None))
            .order_by(OutboxEvent.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for event in events:
        handler = handlers.get(event.event_type)
        if handler is not None:
            try:
                async with db.begin_nested():
                    await handler(db, settings, event)
            except Exception as e:
                event.error = f"{type(e).__name__}: {e}"
                log.exception("evento_falhou", event_id=event.id, event_type=event.event_type)
        event.processed_at = func.now()
    await db.commit()
    return len(events)


def retry_delay(attempts: int) -> timedelta:
    """Espera antes da próxima tentativa: 30 s, 2 min, 8 min, 32 min."""
    return timedelta(seconds=30 * 4 ** (attempts - 1))


async def run_next(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings, tasks: Mapping[str, Task]
) -> bool:
    """Pega a próxima tarefa pronta e a executa. Devolve False se não havia nenhuma.

    A linha fica travada até o fim (FOR UPDATE SKIP LOCKED): outro worker a pula, e se este cair
    a transação é desfeita e a tarefa volta para a fila. A tarefa roda numa sessão própria, então
    a entrega é "pelo menos uma vez": se o commit final falhar, ela roda de novo.
    """
    async with sessionmaker() as db:
        job = await db.scalar(
            select(Job)
            .where(Job.status == "queued", Job.run_after <= func.now())
            .order_by(Job.run_after, Job.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return False
        job.attempts += 1
        try:
            async with sessionmaker() as session:
                await tasks[job.task](session, settings, job.args)
        except Exception as e:
            job.last_error = f"{type(e).__name__}: {e}"
            if job.attempts >= job.max_attempts:
                job.status = "failed"
                job.finished_at = func.now()
                log.exception("tarefa_falhou", job_id=job.id, task=job.task, attempts=job.attempts)
            else:
                job.run_after = func.now() + retry_delay(job.attempts)
                log.warning(
                    "tarefa_vai_tentar_de_novo",
                    job_id=job.id,
                    task=job.task,
                    attempts=job.attempts,
                    error=job.last_error,
                )
        else:
            job.status = "done"
            job.finished_at = func.now()
            log.info("tarefa_concluida", job_id=job.id, task=job.task)
        await db.commit()
        return True


async def schedule(db: AsyncSession, routines: Mapping[str, time], now: datetime) -> None:
    """Agenda as rotinas do dia (em São Paulo), no horário de cada uma. A `dedup_key` garante uma
    por dia, mesmo com dois workers; um worker que sobe depois do horário a roda na hora."""
    day = now.astimezone(TZ).date()
    keys = {f"{task}:{day.isoformat()}": task for task in routines}
    existing = set((await db.scalars(select(Job.dedup_key).where(Job.dedup_key.in_(keys)))).all())
    missing = [
        {"task": task, "dedup_key": key, "run_after": datetime.combine(day, routines[task], TZ)}
        for key, task in keys.items()
        if key not in existing
    ]
    if missing:
        await db.execute(
            insert(Job).values(missing).on_conflict_do_nothing(index_elements=["dedup_key"])
        )
    await db.commit()


async def cleanup(db: AsyncSession, _settings: Settings, _args: dict[str, Any]) -> None:
    """Rotina diária: sem ela, a fila, o outbox e as Idempotency-Key crescem para sempre."""
    await db.execute(delete(OutboxEvent).where(OutboxEvent.processed_at < func.now() - KEEP_DONE))
    await db.execute(
        delete(IdempotencyKey).where(IdempotencyKey.created_at < func.now() - idempotency.KEEP)
    )
    await db.execute(
        delete(Job).where(
            or_(
                and_(Job.status == "done", Job.finished_at < func.now() - KEEP_DONE),
                and_(Job.status == "failed", Job.finished_at < func.now() - KEEP_FAILED),
            )
        )
    )
    await db.commit()
