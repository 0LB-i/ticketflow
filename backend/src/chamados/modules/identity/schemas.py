import uuid
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=1024)


class ForgotIn(BaseModel):
    email: EmailStr


class TokenPasswordIn(BaseModel):
    token: str = Field(max_length=200)
    password: str = Field(max_length=1024)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(max_length=1024)


class TokenInfo(BaseModel):
    purpose: Literal["invite", "password_reset"]
    email: str
    full_name: str


class MeTeam(BaseModel):
    id: uuid.UUID
    name: str
    role: Literal["member", "supervisor"]


class Me(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    teams: list[MeTeam]
    permissions: list[str]
