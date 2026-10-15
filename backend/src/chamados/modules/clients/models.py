import uuid
from datetime import date, datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Identity,
    Index,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from chamados.db.base import Base


class Client(Base):
    """Cliente atendido: pessoa física (CPF) ou jurídica (CNPJ). Não tem login no sistema.

    Os documentos, telefones e o CEP ficam só com dígitos (e letras, no CNPJ alfanumérico);
    a interface formata para exibir. Só o CEP, a cidade e a UF são obrigatórios.
    """

    __tablename__ = "clients"
    __table_args__ = (
        CheckConstraint("kind IN ('person', 'company')", name="kind"),
        CheckConstraint("length(state) = 2", name="state"),
        Index("clients_name_idx", text("lower(name)")),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID, unique=True, server_default=text("gen_random_uuid()")
    )
    kind: Mapped[str] = mapped_column(Text)  # person (CPF) · company (CNPJ)
    name: Mapped[str | None] = mapped_column(Text)  # nome completo ou razão social
    trade_name: Mapped[str | None] = mapped_column(Text)  # nome fantasia
    document: Mapped[str | None] = mapped_column(Text, unique=True)  # CPF ou CNPJ
    id_number: Mapped[str | None] = mapped_column(Text)  # RG
    birth_date: Mapped[date | None] = mapped_column(Date)
    state_registration: Mapped[str | None] = mapped_column(Text)  # inscrição estadual
    municipal_registration: Mapped[str | None] = mapped_column(Text)  # inscrição municipal
    contact_name: Mapped[str | None] = mapped_column(Text)  # pessoa de contato na empresa
    emails: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    phones: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    postal_code: Mapped[str] = mapped_column(Text)
    street: Mapped[str | None] = mapped_column(Text)
    number: Mapped[str | None] = mapped_column(Text)
    complement: Mapped[str | None] = mapped_column(Text)
    district: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @property
    def label(self) -> str:
        """Como o cliente aparece nas listas e no chamado, mesmo sem nome."""
        return self.name or self.trade_name or f"{self.city}/{self.state}"
