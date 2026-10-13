import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
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


class Attachment(Base):
    """Arquivo enviado. Sem chamado, é um envio ainda não vinculado (apagado depois de 24 h).

    O nome original fica só aqui; no disco o arquivo tem um nome aleatório (`storage_key`).
    """

    __tablename__ = "attachments"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="size_bytes"),
        CheckConstraint("comment_id IS NULL OR ticket_id IS NOT NULL", name="comment_needs_ticket"),
        CheckConstraint("(linked_at IS NULL) = (ticket_id IS NULL)", name="linked"),
        Index(
            "attachments_ticket_idx", "ticket_id", postgresql_where=text("ticket_id IS NOT NULL")
        ),
        Index("attachments_orphans_idx", "created_at", postgresql_where=text("linked_at IS NULL")),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID, unique=True, server_default=text("gen_random_uuid()")
    )
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"))
    comment_id: Mapped[int | None] = mapped_column(
        ForeignKey("ticket_comments.id", ondelete="CASCADE")
    )
    filename: Mapped[str] = mapped_column(Text)  # nome original, saneado
    content_type: Mapped[str] = mapped_column(Text)  # pela extensão conferida, não pelo navegador
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(Text, unique=True)  # attachments/AAAA/MM/<uuid>
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    uploader: Mapped[User] = relationship(lazy="joined")
