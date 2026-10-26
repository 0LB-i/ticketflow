"""Modelos de relatório salvos (docs/14 §14.8.1): pessoais, só o dono vê e altera. O commit fica
com quem chama."""

import uuid

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from chamados.modules.identity.deps import Auth
from chamados.modules.reports.builder import MAX_MODELS, ReportConfig, check_block, upgrade
from chamados.modules.reports.models import ReportModel

MAX_NAME = 80


async def list_mine(db: AsyncSession, auth: Auth) -> list[ReportModel]:
    return list(
        await db.scalars(
            select(ReportModel)
            .where(ReportModel.owner_id == auth.user.id)
            .order_by(func.lower(ReportModel.name))
        )
    )


async def get(db: AsyncSession, auth: Auth, public_id: uuid.UUID) -> ReportModel:
    """O modelo da pessoa; o de outra pessoa responde como se não existisse."""
    model = await db.scalar(
        select(ReportModel).where(
            ReportModel.public_id == public_id, ReportModel.owner_id == auth.user.id
        )
    )
    if model is None:
        raise HTTPException(404, "Modelo não encontrado.")
    return model


def config_of(model: ReportModel) -> ReportConfig:
    """A configuração do modelo, convertida se foi salva num formato antigo (`builder.upgrade`);
    ela só é gravada no formato novo quando o modelo for salvo de novo."""
    try:
        return ReportConfig.model_validate(upgrade(model.config))
    except ValidationError:
        raise HTTPException(422, "Este modelo foi salvo num formato que não vale mais.") from None


async def save(
    db: AsyncSession,
    auth: Auth,
    model: ReportModel | None,
    *,
    name: str,
    config: ReportConfig,
    is_default: bool,
) -> ReportModel:
    """Cria (`model` None) ou altera um modelo da pessoa."""
    name = name.strip()
    if not name:
        raise HTTPException(422, "Informe o nome do modelo.")
    if len(name) > MAX_NAME:
        raise HTTPException(422, "O nome do modelo pode ter no máximo 80 caracteres.")
    for block in config.blocks:
        check_block(block)
    owner = auth.user.id
    same_name = select(ReportModel.id).where(
        ReportModel.owner_id == owner, func.lower(ReportModel.name) == name.lower()
    )
    if model is not None:
        same_name = same_name.where(ReportModel.id != model.id)
    if await db.scalar(same_name) is not None:
        raise HTTPException(409, "Você já tem um modelo com este nome.")
    if model is None:
        count = await db.scalar(
            select(func.count()).select_from(ReportModel).where(ReportModel.owner_id == owner)
        )
        if (count or 0) >= MAX_MODELS:
            raise HTTPException(422, "Você chegou ao limite de 50 modelos.")
    if is_default:  # um só modelo inicial: o anterior deixa de ser
        others = update(ReportModel).where(ReportModel.owner_id == owner, ReportModel.is_default)
        if model is not None:
            others = others.where(ReportModel.id != model.id)
        await db.execute(others.values(is_default=False))
    if model is None:
        model = ReportModel(owner_id=owner)
        db.add(model)
    model.name = name
    model.config = config.model_dump(mode="json")
    model.is_default = is_default
    await db.flush()
    return model


async def save_filters(db: AsyncSession, model: ReportModel, config: ReportConfig) -> None:
    """Troca o período e os filtros salvos, sem mexer nos blocos."""
    current = config_of(model)
    model.config = current.model_copy(
        update={"period": config.period, "filters": config.filters}
    ).model_dump(mode="json")
    await db.flush()


async def delete(db: AsyncSession, model: ReportModel) -> None:
    await db.delete(model)
    await db.flush()
