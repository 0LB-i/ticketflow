"""Papéis, grupos e setores atendidos (docs/08)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from chamados.db.base import Base


class Role(Base):
    """Papel global. Os do sistema (agent, admin, auditor) vêm da migração."""

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(SmallInteger, Identity(always=True), primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    permissions: Mapped[list[str]] = mapped_column(ARRAY(Text))
    is_system: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Department(Base):
    """Setor atendido: só classificação e relatórios, sem login (docs/08 §8.1)."""

    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("parent_id", "name", postgresql_nulls_not_distinct=True),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID, unique=True, server_default=text("gen_random_uuid()")
    )
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    name: Mapped[str] = mapped_column(Text)
    code: Mapped[str | None] = mapped_column(Text, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    parent: Mapped["Department | None"] = relationship(remote_side=[id])


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (
        CheckConstraint(
            "notify_on_new IN ('queue_only', 'email_all_members')", name="notify_on_new"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID, unique=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(Text, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    notify_on_new: Mapped[str] = mapped_column(Text, server_default=text("'queue_only'"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    members: Mapped[list["TeamMember"]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (
        CheckConstraint("role IN ('member', 'supervisor')", name="role"),
        CheckConstraint("source IN ('manual', 'idp')", name="source"),
    )

    team_id: Mapped[int] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(Text, server_default=text("'member'"))
    source: Mapped[str] = mapped_column(Text, server_default=text("'manual'"))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    team: Mapped[Team] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(back_populates="memberships")  # type: ignore[name-defined]  # noqa: F821
