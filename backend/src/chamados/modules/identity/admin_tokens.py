"""Tokens de API (docs/05): só quem administra os usuários cria (no próprio nome), vê os tokens
ativos de todas as pessoas e revoga qualquer um. Nenhum token entra aqui (`require`)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import contains_eager

from chamados.core.permissions import P
from chamados.db.session import DB
from chamados.modules.identity.deps import Auth, require
from chamados.modules.identity.models import ApiToken, User
from chamados.modules.identity.schemas import ApiTokenCreated, ApiTokenIn, ApiTokenOut
from chamados.modules.identity.tokens import issue_api_token, revoke_api_token

router = APIRouter(prefix="/admin/api-tokens", tags=["usuários"])
Admin = Annotated[Auth, Depends(require(P.ADMIN_USERS))]


class TokenOwner(BaseModel):
    id: uuid.UUID
    display_name: str
    email: str | None
    is_active: bool


class AdminApiTokenOut(ApiTokenOut):
    user: TokenOwner


class AdminApiTokenList(BaseModel):
    items: list[AdminApiTokenOut]


@router.get("", response_model=AdminApiTokenList)
async def list_api_tokens(
    _: Admin,
    db: DB,
    user: Annotated[uuid.UUID | None, Query(description="só os desta pessoa")] = None,
) -> AdminApiTokenList:
    """Os tokens não revogados (os vencidos também), pela pessoa e do mais novo ao mais antigo."""
    stmt = (
        select(ApiToken)
        .join(ApiToken.user)
        .options(contains_eager(ApiToken.user))
        .where(ApiToken.revoked_at.is_(None))
        .order_by(User.display_name, ApiToken.created_at.desc(), ApiToken.id.desc())
    )
    if user is not None:
        stmt = stmt.where(User.public_id == user)
    return AdminApiTokenList(
        items=[
            AdminApiTokenOut(
                id=t.public_id,
                name=t.name,
                scope=t.scope,
                created_at=t.created_at,
                expires_at=t.expires_at,
                last_used_at=t.last_used_at,
                user=TokenOwner(
                    id=t.user.public_id,
                    display_name=t.user.display_name,
                    email=t.user.email,
                    is_active=t.user.is_active,
                ),
            )
            for t in await db.scalars(stmt)
        ]
    )


@router.post("", response_model=ApiTokenCreated, status_code=201)
async def create_api_token(
    data: ApiTokenIn, auth: Admin, db: DB, request: Request
) -> ApiTokenCreated:
    """Um token no nome de quem cria; o valor vem só nesta resposta."""
    name = data.name.strip()
    if not name:
        raise HTTPException(422, "Dê um nome ao token.")
    raw, token = issue_api_token(
        db, auth.user, name, data.scope, data.days, actor_user_id=auth.user.id, request=request
    )
    await db.commit()
    await db.refresh(token)
    return ApiTokenCreated(
        id=token.public_id,
        name=token.name,
        scope=token.scope,
        created_at=token.created_at,
        expires_at=token.expires_at,
        last_used_at=token.last_used_at,
        token=raw,
    )


@router.delete("/{token_id}", status_code=204)
async def revoke_any_api_token(token_id: uuid.UUID, auth: Admin, db: DB, request: Request) -> None:
    token = await db.scalar(
        select(ApiToken).where(ApiToken.public_id == token_id, ApiToken.revoked_at.is_(None))
    )
    if token is None:
        raise HTTPException(404, "Token não encontrado.")
    revoke_api_token(db, token, actor_user_id=auth.user.id, request=request)
    await db.commit()
