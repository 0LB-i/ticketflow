"""Configurações gerais da instalação (docs/13: /admin/configuracoes) e as vigências do
expediente (docs/14 §14.7)."""

from datetime import date, datetime, time
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    SmallInteger,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from chamados.db.base import Base


class SystemSetting(Base):
    """Uma configuração por chave (ex.: "locale", "colors", "logo"); sem a linha, vale o padrão."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WorkSchedule(Base):
    """Uma vigência do expediente: da instalação (sem pessoa nem grupo), de um grupo ou de uma
    pessoa, a partir de `valid_from` (nulo: desde sempre) até a próxima do mesmo dono. Sem dias
    e horário, a pessoa ou o grupo volta a seguir o de cima (o do grupo ou o da instalação).
    O intervalo (`break_start`–`break_end`, opcional) fica dentro do horário e fora do expediente.
    Mudar o expediente grava uma vigência nova (a da mesma data é substituída): a hora extra dos
    dias de antes continua a mesma."""

    __tablename__ = "work_schedules"
    __table_args__ = (
        CheckConstraint("user_id IS NULL OR team_id IS NULL", name="owner"),
        CheckConstraint(
            '(weekdays IS NULL) = (start IS NULL) AND (start IS NULL) = ("end" IS NULL)',
            name="hours",
        ),
        CheckConstraint(
            "weekdays IS NOT NULL OR user_id IS NOT NULL OR team_id IS NOT NULL",
            name="installation",
        ),
        CheckConstraint('"end" > start', name="range"),
        CheckConstraint(
            "(break_start IS NULL) = (break_end IS NULL) AND (break_start IS NULL OR "
            '(start < break_start AND break_start < break_end AND break_end < "end"))',
            name="break",
        ),
        CheckConstraint("weekdays <@ '{0,1,2,3,4,5,6}'::smallint[]", name="weekdays"),
        # Uma vigência por dono e data; o "desde sempre" (nulo) também é um só.
        UniqueConstraint("user_id", "team_id", "valid_from", postgresql_nulls_not_distinct=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    # RESTRICT: pessoas e grupos não são apagados, só desativados (regra 5).
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="RESTRICT"))
    valid_from: Mapped[date | None] = mapped_column(Date)
    weekdays: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger))  # 0 = segunda
    start: Mapped[time | None] = mapped_column(Time)
    end: Mapped[time | None] = mapped_column(Time)
    break_start: Mapped[time | None] = mapped_column(Time)
    break_end: Mapped[time | None] = mapped_column(Time)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
