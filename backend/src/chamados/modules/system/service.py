"""Leitura e gravação das configurações, e o idioma efetivo de cada usuário."""

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from chamados.core.i18n import DEFAULT_LOCALE, LOCALES, Locale
from chamados.modules.identity.models import User
from chamados.modules.system.models import SystemSetting


async def get_value(db: AsyncSession, key: str) -> Any:
    return await db.scalar(select(SystemSetting.value).where(SystemSetting.key == key))


async def set_value(db: AsyncSession, key: str, value: Any, user_id: int) -> None:
    """Grava a configuração; `None` apaga a linha e volta ao padrão."""
    if value is None:
        await db.execute(delete(SystemSetting).where(SystemSetting.key == key))
        return
    setting = await db.get(SystemSetting, key)
    if setting is None:
        db.add(SystemSetting(key=key, value=value, updated_by=user_id))
    else:
        setting.value = value
        setting.updated_by = user_id


async def user_locale(db: AsyncSession, user: User) -> Locale:
    """Idioma da pessoa (e-mails): o que ela escolheu ou o padrão do sistema."""
    for locale in (user.locale, await get_value(db, "locale")):
        if locale in LOCALES:
            return locale
    return DEFAULT_LOCALE
