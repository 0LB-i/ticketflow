"""Números do WhatsApp (canais), os responsáveis, as conversas e as mensagens.

As mensagens ficam guardadas aqui porque o WhatsApp não as guarda para buscar depois: os
servidores apagam a mensagem quando ela é entregue, e o histórico chega uma vez só, no pareamento.
"""

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
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from chamados.db.base import Base
from chamados.modules.identity.models import User
from chamados.modules.organization.models import Team

STATES = ("new", "pairing", "connected", "disconnected", "logged_out")
KINDS = (
    "text",
    "image",
    "video",
    "gif",
    "audio",
    "voice",
    "document",
    "sticker",
    "location",
    "contact",
    "poll",
    "other",
)
STATUSES = ("pending", "sent", "failed", "received")


class WhatsAppChannel(Base):
    """Um número ligado ao TicketFlow. Os membros do grupo (`team_id`) veem e respondem as
    conversas; `state` é o último estado que a ponte informou."""

    __tablename__ = "whatsapp_channels"
    __table_args__ = (
        CheckConstraint("length(name) BETWEEN 1 AND 100", name="name"),
        CheckConstraint(f"state IN {STATES}", name="state"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID, unique=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(Text)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    phone: Mapped[str | None] = mapped_column(Text)  # o número pareado (só dígitos)
    state: Mapped[str] = mapped_column(Text, server_default=text("'new'"))
    # O nome de quem respondeu em negrito no começo da mensagem (*Ana:*), para o cliente saber.
    sign_messages: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    team: Mapped[Team] = relationship(lazy="joined")
    managers: Mapped[list["WhatsAppChannelManager"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan"
    )


class WhatsAppChannelManager(Base):
    """Responsável pelo número: decide quem do grupo tem acesso a cada conversa (fase 2)."""

    __tablename__ = "whatsapp_channel_managers"

    channel_id: Mapped[int] = mapped_column(
        ForeignKey("whatsapp_channels.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )

    user: Mapped[User] = relationship(lazy="joined")


class WhatsAppChat(Base):
    """Uma conversa do número: com um contato ou um grupo do WhatsApp (`jid` termina em @g.us)."""

    __tablename__ = "whatsapp_chats"
    __table_args__ = (
        UniqueConstraint("channel_id", "jid"),
        # A lista de conversas: as mais recentes primeiro.
        Index("whatsapp_chats_recent_idx", "channel_id", text("last_message_at DESC NULLS LAST")),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID, unique=True, server_default=text("gen_random_uuid()")
    )
    channel_id: Mapped[int] = mapped_column(ForeignKey("whatsapp_channels.id", ondelete="CASCADE"))
    jid: Mapped[str] = mapped_column(Text)
    is_group: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    name: Mapped[str | None] = mapped_column(Text)  # do contato, do grupo ou o pushName
    unread: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WhatsAppMessage(Base):
    """Mensagem de uma conversa. `wa_id` é o id do WhatsApp (o das enviadas daqui é gerado pelo
    TicketFlow antes do envio, e a cópia que a ponte devolve é ignorada pelo índice único).
    `author_id`: quem do TicketFlow mandou; nossa sem autor = mandada pelo celular."""

    __tablename__ = "whatsapp_messages"
    __table_args__ = (
        UniqueConstraint("chat_id", "wa_id"),
        CheckConstraint(f"kind IN {KINDS}", name="kind"),
        CheckConstraint(f"status IN {STATUSES}", name="status"),
        # A conversa aberta: as mensagens da mais nova para trás.
        Index("whatsapp_messages_chat_idx", "chat_id", text("sent_at DESC"), text("id DESC")),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("whatsapp_chats.id", ondelete="CASCADE"))
    wa_id: Mapped[str] = mapped_column(Text)
    from_me: Mapped[bool] = mapped_column(Boolean)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    sender_jid: Mapped[str | None] = mapped_column(Text)  # no grupo, quem mandou
    sender_name: Mapped[str | None] = mapped_column(Text)  # o pushName de quem mandou
    kind: Mapped[str] = mapped_column(Text, server_default=text("'text'"))
    body: Mapped[str | None] = mapped_column(Text)  # o texto ou a legenda, sem a assinatura
    file_name: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    author: Mapped[User | None] = relationship(lazy="joined")
