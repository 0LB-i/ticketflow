"""Expediente da empresa: dias, horário e feriados. O tempo de tarefa fora dele é hora extra
(docs/14 §14.7)."""

from datetime import date, time
from typing import Annotated

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from chamados.modules.system.service import get_value


class WorkHours(BaseModel):
    weekdays: list[Annotated[int, Field(ge=0, le=6)]] = Field(
        max_length=7, description="dias de trabalho: 0 = segunda … 6 = domingo"
    )
    start: time = Field(description="início do expediente (hora de São Paulo)")
    end: time = Field(description="fim do expediente; depois do início")
    holidays: list[date] = Field(default=[], max_length=200, description="feriados e folgas")


DEFAULT = WorkHours(weekdays=[0, 1, 2, 3, 4], start=time(8), end=time(18))


async def get_work_hours(db: AsyncSession) -> WorkHours:
    value = await get_value(db, "work_hours")
    return WorkHours.model_validate(value) if value else DEFAULT
