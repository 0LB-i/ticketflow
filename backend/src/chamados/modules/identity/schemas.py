import uuid
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from chamados.core.i18n import Locale


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
    full_name: str


class MeTeam(BaseModel):
    id: uuid.UUID
    name: str
    role: Literal["member", "supervisor"]


class Me(BaseModel):
    id: uuid.UUID
    email: str | None
    username: str | None
    full_name: str
    must_change_password: bool
    role: str
    teams: list[MeTeam]
    permissions: list[str]
    locale: Locale | None = Field(description="idioma escolhido; nulo segue o padrão do sistema")


class MeUpdate(BaseModel):
    locale: Locale | None = Field(description="nulo volta ao idioma padrão do sistema")
