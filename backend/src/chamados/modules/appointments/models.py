"""Compromissos da agenda e os participantes de cada um."""

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
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from chamados.db.base import Base
from chamados.modules.identity.models import User


class Appointment(Base):
    """Compromisso: quem criou (o dono, o único que altera) e o chamado, se houver. O dia inteiro
    vai da meia-noite do primeiro dia à do dia seguinte ao último, no fuso da máquina."""

    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint("length(title) BETWEEN 1 AND 200", name="title"),
        CheckConstraint("ends_at > starts_at", name="period"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID, unique=True, server_default=text("gen_random_uuid()")
    )
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    all_day: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id"), index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped[User] = relationship(lazy="joined")
    attendees: Mapped[list["AppointmentAttendee"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan"
    )


class AppointmentAttendee(Base):
    """Quem vê o compromisso na agenda (o dono também). `alert_seen_at`: quando a pessoa abriu a
    agenda com o aviso dele aceso; mudar o horário apaga, e o aviso acende de novo."""

    __tablename__ = "appointment_attendees"
    __table_args__ = (Index("appointment_attendees_user_idx", "user_id", "appointment_id"),)

    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    alert_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(lazy="joined")
