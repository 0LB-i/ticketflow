import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Identity, Index, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from chamados.db.base import Base


class ReportModel(Base):
    """Modelo de relatório pessoal (docs/14 §14.8.1): guarda a configuração (`builder.ReportConfig`
    em JSON), nunca os números. Só o dono vê; apagar é de verdade (nada aponta para ele)."""

    __tablename__ = "report_models"
    __table_args__ = (
        Index("report_models_owner_id_name_key", "owner_id", func.lower(text("name")), unique=True),
        # No máximo um modelo inicial por pessoa.
        Index(
            "report_models_owner_id_default_key",
            "owner_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID, unique=True, server_default=text("gen_random_uuid()")
    )
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    is_default: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
