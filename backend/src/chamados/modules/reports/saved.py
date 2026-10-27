"""Modelos de relatório salvos (docs/14 §14.8.1): pessoais, só o dono vê e altera. O commit fica
com quem chama."""

import uuid

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from chamados.modules.identity.deps import Auth
from chamados.modules.reports.builder import (
    BUILTINS,
    MAX_MODELS,
    ReportConfig,
    check_block,
    upgrade,
)
from chamados.modules.reports.models import ReportModel, ReportPreference

MAX_NAME = 80
MAX_TABS = MAX_MODELS + len(BUILTINS)


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


class TabPrefs(BaseModel):
    """A preferência de abas da pessoa (`report_preferences.tabs`): os ids na ordem (slugs dos
    prontos e `public_id` dos modelos) e os escondidos."""

    model_config = ConfigDict(extra="forbid")

    order: list[str] = Field(default=[], max_length=MAX_TABS)
    hidden: list[str] = Field(default=[], max_length=MAX_TABS)


async def tab_prefs(db: AsyncSession, auth: Auth) -> TabPrefs | None:
    """A preferência da pessoa; sem ela (ou num formato que não vale mais), None."""
    stored = await db.scalar(
        select(ReportPreference.tabs).where(ReportPreference.user_id == auth.user.id)
    )
    if stored is None:
        return None
    try:
        return TabPrefs.model_validate(stored)
    except ValidationError:
        return None


async def save_tabs(db: AsyncSession, auth: Auth, prefs: TabPrefs) -> None:
    """Grava a preferência da pessoa (cria a linha na primeira vez)."""
    tabs = prefs.model_dump()
    await db.execute(
        insert(ReportPreference)
        .values(user_id=auth.user.id, tabs=tabs)
        .on_conflict_do_update(
            index_elements=[ReportPreference.user_id],
            set_={"tabs": tabs, "updated_at": func.now()},
        )
    )


def arrange(ids: list[str], default: str | None, prefs: TabPrefs | None) -> list[tuple[str, bool]]:
    """As abas na ordem da pessoa, com se aparecem. `ids`: a ordem de sempre (os prontos, depois
    os modelos pelo nome); um id da preferência que não existe mais fica de fora e um modelo novo,
    que ela ainda não tem, entra no fim. O inicial (`default`, o modelo marcado como inicial, ou,
    sem ele, a primeira aba) sempre aparece."""
    order = list(ids)
    hidden: set[str] = set()
    if prefs is not None:
        known = [i for i in dict.fromkeys(prefs.order) if i in ids]
        order = known + [i for i in ids if i not in known]
        hidden = set(prefs.hidden)
    initial = default if default in order else order[0]
    return [(i, i == initial or i not in hidden) for i in order]
