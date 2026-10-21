from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Identity,
    Index,
    SmallInteger,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from chamados.db.base import Base


class OutboxEvent(Base):
    """Evento de domínio gravado na mesma transação da mudança (transactional outbox). O worker
    o repassa aos handlers, que criam as tarefas; `error` guarda a falha de um handler."""

    __tablename__ = "outbox"
    __table_args__ = (
        Index("outbox_pending_idx", "id", postgresql_where=text("processed_at IS NULL")),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    event_type: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class Job(Base):
    """Tarefa da fila. Enquanto roda, a linha fica travada (FOR UPDATE SKIP LOCKED): se o worker
    cair, a transação é desfeita e a tarefa volta sozinha para a fila."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'done', 'failed')", name="status"),
        Index("jobs_ready_idx", "run_after", postgresql_where=text("status = 'queued'")),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    task: Mapped[str] = mapped_column(Text)  # ex.: attachments.purge
    args: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    status: Mapped[str] = mapped_column(Text, server_default="queued")
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    max_attempts: Mapped[int] = mapped_column(SmallInteger, server_default="5")
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Rotina periódica: uma por dia (`attachments.purge:2026-10-21`), mesmo com dois workers.
    dedup_key: Mapped[str | None] = mapped_column(Text, unique=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
