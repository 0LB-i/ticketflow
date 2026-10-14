"""Categorias, status e códigos de resolução (docs/08 §8.1, docs/10 §10.5)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from chamados.db.base import Base
from chamados.modules.organization.models import Team

TICKET_TYPES = ("incident", "request", "task")
STATUS_KINDS = ("approval", "open", "waiting", "closed", "canceled")


class Category(Base):
    """O que é a tarefa. Árvore de até 3 níveis; não se apaga, só se desativa."""

    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("parent_id", "name", postgresql_nulls_not_distinct=True),
        CheckConstraint(f"default_type IN {TICKET_TYPES}", name="default_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID, unique=True, server_default=text("gen_random_uuid()")
    )
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    default_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    default_type: Mapped[str] = mapped_column(Text, server_default=text("'incident'"))
    # Restringe a visibilidade às regras 1, 3, 4 e 6 do docs/08 §8.4.
    is_confidential: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    default_team: Mapped[Team | None] = relationship(lazy="joined")


class TicketStatus(Base):
    """As regras dependem do `kind`; o nome é só o rótulo exibido."""

    __tablename__ = "ticket_statuses"
    __table_args__ = (
        CheckConstraint(f"kind IN {STATUS_KINDS}", name="kind"),
        Index(
            "ticket_statuses_default_idx",
            "kind",
            unique=True,
            postgresql_where=text("is_default_for_kind"),
        ),
    )

    id: Mapped[int] = mapped_column(SmallInteger, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    kind: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    # Status usado quando o fluxo leva a este kind (um por kind).
    is_default_for_kind: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    # Revisão do supervisor: daqui, só ele (ou o admin) leva o chamado a um status concluído.
    is_review: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class ResolutionCode(Base):
    __tablename__ = "resolution_codes"

    id: Mapped[int] = mapped_column(SmallInteger, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
