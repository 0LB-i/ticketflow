from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from chamados.db.base import Base


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
