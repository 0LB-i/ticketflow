import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Text,
    func,
    text,
)
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


class ReportPreference(Base):
    """A ordem e as abas escondidas de Relatórios (docs/14 §14.8.1), uma linha por pessoa. Sem a
    linha, vale a ordem de sempre (`saved.arrange`). Só a própria pessoa lê e grava."""

    __tablename__ = "report_preferences"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # `saved.TabPrefs`: os ids das abas na ordem (slugs dos prontos e `public_id` dos modelos) e
    # os escondidos.
    tabs: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReportExport(Base):
    """Um PDF da aba Clientes baixado com um cliente só (docs/14 §14.7): o Histórico de quem o
    gerou e a cascata (os clientes com relatório no dia saem da lista dela). Guarda os
    parâmetros para gerar de novo (com as datas do período), não o arquivo."""

    __tablename__ = "report_exports"
    __table_args__ = (
        CheckConstraint("kind IN ('simple', 'detailed')", name="kind"),
        Index("report_exports_user_id_created_at_idx", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    kind: Mapped[str] = mapped_column(Text)  # simple (simplificado) · detailed (detalhado)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    query: Mapped[dict[str, Any]] = mapped_column(JSONB)  # os parâmetros do /relatorios/pdf
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
