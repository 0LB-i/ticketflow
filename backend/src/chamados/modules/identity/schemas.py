import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from chamados.core.i18n import Locale
from chamados.modules.identity.token_access import PERMISSIONS, ordered


class LoginIn(BaseModel):
    login: str = Field(min_length=1, max_length=254, description="e-mail ou nome de usuário")
    password: str = Field(max_length=1024)


class ForgotIn(BaseModel):
    email: EmailStr


class TokenPasswordIn(BaseModel):
    token: str = Field(max_length=200)
    password: str = Field(max_length=1024)


class ChangePasswordIn(BaseModel):
    # Dispensada na troca obrigatória logo depois do primeiro acesso (senha provisória).
    current_password: str | None = Field(default=None, max_length=1024)
    new_password: str = Field(max_length=1024)


class TokenInfo(BaseModel):
    purpose: Literal["invite", "password_reset"]
    email: str | None
    display_name: str


class MeTeam(BaseModel):
    id: uuid.UUID
    name: str
    role: Literal["member", "supervisor"]


class Me(BaseModel):
    id: uuid.UUID
    email: str | None
    username: str | None
    display_name: str
    must_change_password: bool
    role: str
    teams: list[MeTeam]
    permissions: list[str]
    locale: Locale | None = Field(description="idioma escolhido; nulo segue o padrão do sistema")


class MeUpdate(BaseModel):
    locale: Locale | None = Field(description="nulo volta ao idioma padrão do sistema")


class ApiTokenPermissionsIn(BaseModel):
    permissions: list[str] = Field(
        description="o que o token pode fazer: `área.ação` (ex.: tickets.view, users.create)"
    )

    @field_validator("permissions")
    @classmethod
    def _known(cls, value: list[str]) -> list[str]:
        if unknown := sorted(set(value) - PERMISSIONS):
            raise ValueError(f"permissões que não existem: {', '.join(unknown)}")
        return ordered(set(value))


class ApiTokenIn(ApiTokenPermissionsIn):
    name: str = Field(min_length=1, max_length=100, description="para que serve (ex.: Claude Code)")
    days: int | None = Field(default=90, ge=1, le=365, description="validade em dias; null: sem")


class ApiTokenOut(BaseModel):
    id: uuid.UUID
    name: str
    permissions: list[str]
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None


class ApiTokenCreated(ApiTokenOut):
    token: str = Field(description="o valor, mostrado só nesta resposta")
