"""Usuários, sessões, tokens de uso único (docs/09), tokens de API e Idempotency-Key (docs/05)."""

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
from sqlalchemy.dialects.postgresql import BYTEA, CITEXT, INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from chamados.db.base import Base
from chamados.modules.organization.models import Role, TeamMember


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID, unique=True, server_default=text("gen_random_uuid()")
    )
    # Login por e-mail ou por nome de usuário. O administrador padrão só tem usuário ("admin").
    email: Mapped[str | None] = mapped_column(CITEXT, unique=True)
    username: Mapped[str | None] = mapped_column(CITEXT, unique=True)
    full_name: Mapped[str] = mapped_column(Text)
    # O nome que aparece no sistema; o completo fica no cadastro (tela de Usuários, auditoria).
    display_name: Mapped[str] = mapped_column(Text)
    role_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("roles.id"))
    password_hash: Mapped[str | None] = mapped_column(Text)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Senha provisória (admin/admin na instalação): a API só libera o uso depois da troca.
    must_change_password: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    # Excluído: some da lista e dos grupos, sem login nem e-mail; o nome fica no histórico.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Idioma escolhido pela pessoa; nulo segue o padrão do sistema (configurações).
    locale: Mapped[str | None] = mapped_column(Text)
    failed_logins: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    last_failed_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    role: Mapped[Role] = relationship(lazy="joined")
    memberships: Mapped[list[TeamMember]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserSession(Base):
    """Sessão no servidor. O cookie leva só um identificador aleatório; aqui fica o hash."""

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    csrf_token_hash: Mapped[str] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(lazy="joined")


class AuthToken(Base):
    """Convite e redefinição de senha, de uso único (docs/09 §9.4)."""

    __tablename__ = "auth_tokens"
    __table_args__ = (CheckConstraint("purpose IN ('invite', 'password_reset')", name="purpose"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(Text)
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(lazy="joined")


class ApiToken(Base):
    """Token de API (`Authorization: Bearer`): age em nome do usuário, com as permissões dele.
    `read` só permite leitura. Aqui fica só o hash."""

    __tablename__ = "api_tokens"
    __table_args__ = (CheckConstraint("scope IN ('read', 'write')", name="scope"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID, unique=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(Text)
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(lazy="joined")


class IdempotencyKey(Base):
    """`Idempotency-Key` de um POST com token de API (docs/05): a resposta de sucesso fica guardada
    e é repetida, sem executar de novo, para a mesma chave do mesmo token."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("owner_hash", "key"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    # SHA-256 do header Authorization: a chave vale para um token.
    owner_hash: Mapped[str] = mapped_column(Text)
    key: Mapped[str] = mapped_column(Text)
    # SHA-256 do método, do caminho e do corpo: a mesma chave com outra requisição é recusada.
    fingerprint: Mapped[str] = mapped_column(Text)
    # Nulo enquanto a primeira requisição está em andamento.
    status_code: Mapped[int | None] = mapped_column(SmallInteger)
    headers: Mapped[list[list[str]] | None] = mapped_column(JSONB)
    body: Mapped[bytes | None] = mapped_column(BYTEA)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LoginIpFailure(Base):
    """Uma tentativa de login de um IP, que conta como falha até dar certo (`ratelimit.py`).
    UNLOGGED: dado passageiro, mais rápido de gravar; se o PostgreSQL cair, some, como sumia da
    memória quando a API reiniciava."""

    __tablename__ = "login_ip_failures"
    __table_args__ = (Index("login_ip_failures_ip_idx", "ip", "at"), {"prefixes": ["UNLOGGED"]})

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    ip: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
