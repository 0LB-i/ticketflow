"""Chamados, observadores, comentários e histórico (docs/04, docs/10)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Sequence,
    SmallInteger,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from chamados.db.base import Base
from chamados.modules.catalog.models import (
    TICKET_TYPES,
    Category,
    ResolutionCode,
    TicketStatus,
)
from chamados.modules.clients.models import Client
from chamados.modules.identity.models import User
from chamados.modules.organization.models import Department, Team

# Busca textual em português, sem acentos (configuração pt_br da migração 0001).
TICKET_SEARCH = (
    "setweight(to_tsvector('pt_br'::regconfig, title), 'A') || "
    "setweight(to_tsvector('pt_br'::regconfig, description), 'B')"
)
COMMENT_SEARCH = "to_tsvector('pt_br'::regconfig, body)"

ticket_number_seq = Sequence("ticket_number_seq", start=1000, metadata=Base.metadata)


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint("length(title) BETWEEN 3 AND 300", name="title"),
        CheckConstraint(f"type IN {TICKET_TYPES}", name="type"),
        Index("tickets_queue_idx", "team_id", "status_id", "created_at"),
        Index("tickets_assignee_idx", "assignee_id", "status_id"),
        Index("tickets_search_idx", "search_vector", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID, unique=True, server_default=text("gen_random_uuid()")
    )
    number: Mapped[int] = mapped_column(
        BigInteger, ticket_number_seq, unique=True, server_default=ticket_number_seq.next_value()
    )
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, server_default=text("''"))
    type: Mapped[str] = mapped_column(Text)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    # Para quem é a tarefa: setor e pessoa atendidos, sem conta no sistema (docs/08).
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"))
    beneficiary_name: Mapped[str | None] = mapped_column(Text)  # contato: quem pediu, texto livre
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    status_id: Mapped[int] = mapped_column(ForeignKey("ticket_statuses.id"))
    resolution_code_id: Mapped[int | None] = mapped_column(ForeignKey("resolution_codes.id"))
    reopened_count: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    # Quando o trabalho começou: o registro sugere a hora atual, e a pessoa pode ajustar.
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    first_assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    search_vector: Mapped[Any] = mapped_column(
        TSVECTOR, Computed(TICKET_SEARCH, persisted=True), deferred=True
    )

    created_by: Mapped[User] = relationship(foreign_keys=[created_by_id], lazy="joined")
    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_id], lazy="joined")
    team: Mapped[Team] = relationship(lazy="joined")
    category: Mapped[Category | None] = relationship(lazy="joined")
    department: Mapped[Department | None] = relationship(lazy="joined")
    client: Mapped[Client | None] = relationship(lazy="joined")
    status: Mapped[TicketStatus] = relationship(lazy="joined")
    resolution_code: Mapped[ResolutionCode | None] = relationship(lazy="joined")
    watchers: Mapped[list["TicketWatcher"]] = relationship(
        cascade="all, delete-orphan", order_by="TicketWatcher.added_at"
    )
    co_assignees: Mapped[list["TicketCoAssignee"]] = relationship(
        cascade="all, delete-orphan", order_by="TicketCoAssignee.added_at"
    )


class TicketCoAssignee(Base):
    """Outros responsáveis, além do principal (assignee_id): só existem com um principal e saem
    junto com ele (devolver à fila, transferir)."""

    __tablename__ = "ticket_co_assignees"

    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True, index=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(lazy="joined")


class TicketTeam(Base):
    """Grupos que já atuaram no chamado (regra 2 da visibilidade, docs/08 §8.4)."""

    __tablename__ = "ticket_teams"

    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), primary_key=True
    )
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), primary_key=True, index=True)
    first_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TicketWatcher(Base):
    __tablename__ = "ticket_watchers"
    __table_args__ = (CheckConstraint("kind IN ('watcher', 'mentioned')", name="kind"),)

    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    # 'mentioned' = entrou por @menção
    kind: Mapped[str] = mapped_column(Text, server_default=text("'watcher'"))
    added_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(foreign_keys=[user_id], lazy="joined")


class TicketComment(Base):
    """Comentários não se apagam; a versão anterior de uma edição fica em ticket_events."""

    __tablename__ = "ticket_comments"
    __table_args__ = (
        CheckConstraint("length(body) > 0", name="body"),
        CheckConstraint("time_spent_minutes > 0", name="time_spent_minutes"),
        Index("ticket_comments_ticket_idx", "ticket_id", "created_at"),
        Index("ticket_comments_search_idx", "search_vector", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID, unique=True, server_default=text("gen_random_uuid()")
    )
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"))
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    is_solution: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    # Tempo gasto neste andamento: a soma por pessoa é a base da cobrança.
    time_spent_minutes: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    search_vector: Mapped[Any] = mapped_column(
        TSVECTOR, Computed(COMMENT_SEARCH, persisted=True), deferred=True
    )

    author: Mapped[User] = relationship(lazy="joined")


class TicketRead(Base):
    """Última vez que a pessoa abriu o chamado: o que chegou depois é novidade (docs/10 §10.6)."""

    __tablename__ = "ticket_reads"

    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TicketEvent(Base):
    """Histórico do chamado. Só aceita inserção (trigger na migração 0004)."""

    __tablename__ = "ticket_events"
    __table_args__ = (Index("ticket_events_ticket_idx", "ticket_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(Text)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    actor: Mapped[User | None] = relationship(lazy="joined")
