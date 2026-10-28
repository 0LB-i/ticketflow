"""Expediente: dias e horário, com vigências, da instalação, de cada grupo e de cada pessoa, e os
feriados da instalação. O tempo de tarefa fora dele é hora extra (docs/14 §14.7).

Precedência num dia: o da pessoa > o do grupo > o da instalação. O do grupo vale para quem está
em um só grupo (ativo) com expediente nesse dia, pela participação **atual** (não há histórico de
participação); quem está em dois ou mais precisa de um próprio e, até ter, segue o da instalação.
Cada expediente vale a partir de `valid_from` até a próxima vigência do mesmo dono, e uma
vigência sem dias e horário devolve a pessoa ou o grupo ao de cima.
"""

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from functools import lru_cache
from typing import Annotated, Any, Literal

from fastapi import Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chamados.core.timezone import LOCAL_TZ
from chamados.modules.audit.service import record
from chamados.modules.identity.models import User
from chamados.modules.organization.models import Team, TeamMember
from chamados.modules.system.models import WorkSchedule
from chamados.modules.system.service import get_value, set_value

TZ = LOCAL_TZ


class WorkHours(BaseModel):
    """O expediente da instalação (o de um dia) e os feriados: o contrato de `/work-hours`."""

    weekdays: list[Annotated[int, Field(ge=0, le=6)]] = Field(
        max_length=7, description="dias de trabalho: 0 = segunda … 6 = domingo"
    )
    start: time = Field(description="início do expediente (hora da máquina)")
    end: time = Field(description="fim do expediente; depois do início")
    break_start: time | None = Field(
        default=None, description="início do intervalo (fora do expediente); sem ele, sem intervalo"
    )
    break_end: time | None = Field(
        default=None, description="fim do intervalo; entre o início dele e o fim do expediente"
    )
    holidays: list[date] = Field(default=[], max_length=200, description="feriados e folgas")


class WorkHoursIn(WorkHours):
    valid_from: date | None = Field(
        default=None,
        description="a partir de quando vale o horário (sem ele, hoje); os dias antes continuam "
        "com o de antes. Os feriados valem sempre",
    )


@dataclass(frozen=True)
class Schedule:
    """Dias e horário de um expediente (sem os feriados, que são da instalação), com o
    intervalo opcional: o tempo nele fica fora do expediente."""

    weekdays: tuple[int, ...]  # 0 = segunda, em ordem
    start: time
    end: time
    break_start: time | None = None
    break_end: time | None = None

    def periods(self) -> tuple[tuple[time, time], ...]:
        """O horário em faixas: uma, ou duas com o intervalo entre elas."""
        if self.break_start is None or self.break_end is None:
            return ((self.start, self.end),)
        return ((self.start, self.break_start), (self.break_end, self.end))


DEFAULT_SCHEDULE = Schedule((0, 1, 2, 3, 4), time(8), time(18), time(12), time(13, 30))
DEFAULT = WorkHours(
    weekdays=[0, 1, 2, 3, 4],
    start=time(8),
    end=time(18),
    break_start=time(12),
    break_end=time(13, 30),
)

# As vigências de um dono, em ordem: o primeiro dia (date.min: desde sempre) e o expediente (None:
# segue o de cima).
Vigencies = list[tuple[date, Schedule | None]]


def _at(vigencies: Vigencies | None, day: date) -> Schedule | None:
    """O expediente de um dono num dia: o da vigência mais recente que começou até ele."""
    if not vigencies:
        return None
    i = bisect_right(vigencies, day, key=lambda v: v[0]) - 1
    return vigencies[i][1] if i >= 0 else None


def weekday_ranges(weekdays: Sequence[int], names: Sequence[str]) -> str:
    """Os dias em faixas, com os nomes curtos do idioma (`names`, de segunda a domingo):
    "seg–sex", "seg, qua, sex", "seg–qua, sáb". Três ou mais dias seguidos viram uma faixa."""
    days = sorted(set(weekdays))
    parts: list[str] = []
    i = 0
    while i < len(days):
        j = i
        while j + 1 < len(days) and days[j + 1] == days[j] + 1:
            j += 1
        if j - i >= 2:
            parts.append(f"{names[days[i]]}–{names[days[j]]}")
        else:
            parts.extend(names[d] for d in days[i : j + 1])
        i = j + 1
    return ", ".join(parts)


def describe(schedule: Schedule, names: Sequence[str]) -> str:
    """Um expediente em texto curto: "seg–sex 08:00–18:00" ou, com intervalo, "seg–sex
    08:00–12:00, 13:30–18:00"."""
    hours = ", ".join(f"{a:%H:%M}–{b:%H:%M}" for a, b in schedule.periods())
    return f"{weekday_ranges(schedule.weekdays, names)} {hours}"


# As faixas do expediente num dia, em UTC: uma, ou duas com o intervalo entre elas.
Window = tuple[tuple[datetime, datetime], ...]


@lru_cache(maxsize=4096)
def work_window(day: date, schedule: Schedule) -> Window:
    """O expediente do dia em UTC (somar e subtrair datas no mesmo fuso do zoneinfo ignora a
    troca de horário). Em cache: num relatório de um ano, cada dia volta milhares de vezes."""
    return tuple(
        (datetime.combine(day, a, TZ).astimezone(UTC), datetime.combine(day, b, TZ).astimezone(UTC))
        for a, b in schedule.periods()
    )


@dataclass(frozen=True)
class Source:
    """O expediente de uma pessoa num dia e de onde ele vem. `conflict`: os grupos com
    expediente de quem está em dois ou mais (vale o da instalação até ela ter um próprio)."""

    schedule: Schedule
    kind: Literal["own", "team", "installation"]
    team_id: int | None = None
    conflict: tuple[int, ...] = ()


@dataclass
class Calendar:
    """Todas as vigências e as participações nos grupos que têm alguma: são poucas linhas, lidas
    uma vez por requisição (`load_calendar`). Responde o expediente de (pessoa, dia)."""

    installation: Vigencies
    users: dict[int, Vigencies] = field(default_factory=dict)
    teams: dict[int, Vigencies] = field(default_factory=dict)
    member_of: dict[int, tuple[int, ...]] = field(default_factory=dict)  # só grupos com vigência
    holidays: frozenset[date] = frozenset()
    _windows: dict[tuple[int | None, date], Window | None] = field(default_factory=dict, repr=False)

    @property
    def personal(self) -> bool:
        """Se alguém tem um expediente que não é o da instalação (em algum dia)."""
        return bool(self.users or self.member_of)

    def who(self, user_id: int | None) -> int | None:
        """A pessoa, se ela pode ter um expediente que não é o da instalação; senão None (todos
        os outros dividem o mesmo)."""
        if user_id is not None and (user_id in self.users or user_id in self.member_of):
            return user_id
        return None

    def source(self, user_id: int | None, day: date) -> Source:
        """O expediente de uma pessoa num dia (None: o da instalação)."""
        conflict: tuple[int, ...] = ()
        if user_id is not None:
            own = _at(self.users.get(user_id), day)
            if own is not None:
                return Source(own, "own")
            found = [
                (team_id, schedule)
                for team_id in self.member_of.get(user_id, ())
                if (schedule := _at(self.teams[team_id], day)) is not None
            ]
            if len(found) == 1:
                return Source(found[0][1], "team", found[0][0])
            conflict = tuple(team_id for team_id, _ in found)
        installation = _at(self.installation, day) or DEFAULT_SCHEDULE
        return Source(installation, "installation", conflict=conflict)

    def schedule(self, user_id: int | None, day: date) -> Schedule:
        return self.source(self.who(user_id), day).schedule

    def works(self, schedule: Schedule, day: date) -> bool:
        return day.weekday() in schedule.weekdays and day not in self.holidays

    def window(self, user_id: int | None, day: date) -> Window | None:
        """As faixas do expediente de uma pessoa num dia, em UTC; None num dia sem expediente
        (folga ou feriado). Em cache na requisição: a hora extra pergunta por cada tarefa."""
        key = (self.who(user_id), day)
        try:
            return self._windows[key]
        except KeyError:
            schedule = self.source(key[0], day).schedule
            window = work_window(day, schedule) if self.works(schedule, day) else None
            self._windows[key] = window
            return window


def _schedule(row: Any) -> Schedule | None:
    if row.weekdays is None:
        return None
    return Schedule(tuple(sorted(row.weekdays)), row.start, row.end, row.break_start, row.break_end)


async def get_holidays(db: AsyncSession) -> list[date]:
    """Os feriados continuam na chave `work_hours` (a migração 0040 tirou dela o horário)."""
    value = await get_value(db, "work_hours")
    return [date.fromisoformat(d) for d in (value or {}).get("holidays", [])]


async def load_calendar(db: AsyncSession) -> Calendar:
    rows = await db.execute(
        select(
            WorkSchedule.user_id,
            WorkSchedule.team_id,
            WorkSchedule.valid_from,
            WorkSchedule.weekdays,
            WorkSchedule.start,
            WorkSchedule.end,
            WorkSchedule.break_start,
            WorkSchedule.break_end,
        ).order_by(WorkSchedule.valid_from.asc().nulls_first())
    )
    cal = Calendar(installation=[], holidays=frozenset(await get_holidays(db)))
    for row in rows:
        vigency = (row.valid_from or date.min, _schedule(row))
        if row.user_id is not None:
            cal.users.setdefault(row.user_id, []).append(vigency)
        elif row.team_id is not None:
            cal.teams.setdefault(row.team_id, []).append(vigency)
        elif vigency[1] is not None:
            cal.installation.append(vigency)
    if cal.teams:
        member_of: dict[int, list[int]] = {}
        for user_id, team_id in await db.execute(
            select(TeamMember.user_id, TeamMember.team_id)
            .join(Team, Team.id == TeamMember.team_id)
            .where(TeamMember.team_id.in_(cal.teams), Team.is_active)
            .order_by(TeamMember.team_id)
        ):
            member_of.setdefault(user_id, []).append(team_id)
        cal.member_of = {u: tuple(teams) for u, teams in member_of.items()}
    return cal


async def get_work_hours(db: AsyncSession, day: date | None = None) -> WorkHours:
    """O expediente da instalação num dia (sem ele, hoje), com os feriados."""
    day = day or datetime.now(TZ).date()
    row = (
        await db.execute(
            select(
                WorkSchedule.weekdays,
                WorkSchedule.start,
                WorkSchedule.end,
                WorkSchedule.break_start,
                WorkSchedule.break_end,
            )
            .where(
                WorkSchedule.user_id.is_(None),
                WorkSchedule.team_id.is_(None),
                (WorkSchedule.valid_from.is_(None)) | (WorkSchedule.valid_from <= day),
            )
            .order_by(WorkSchedule.valid_from.desc().nulls_last())
            .limit(1)
        )
    ).first()
    schedule = (_schedule(row) if row else None) or DEFAULT_SCHEDULE
    return WorkHours(
        weekdays=list(schedule.weekdays),
        start=schedule.start,
        end=schedule.end,
        break_start=schedule.break_start,
        break_end=schedule.break_end,
        holidays=await get_holidays(db),
    )


async def set_holidays(db: AsyncSession, holidays: list[date], user_id: int) -> None:
    await set_value(
        db, "work_hours", {"holidays": [d.isoformat() for d in sorted(set(holidays))]}, user_id
    )


# --- vigências de um dono (a instalação, um grupo ou uma pessoa) ------------------------------


def _owner(user_id: int | None, team_id: int | None) -> list[Any]:
    return [
        WorkSchedule.user_id.is_(None) if user_id is None else WorkSchedule.user_id == user_id,
        WorkSchedule.team_id.is_(None) if team_id is None else WorkSchedule.team_id == team_id,
    ]


async def vigencies(
    db: AsyncSession, *, user_id: int | None = None, team_id: int | None = None
) -> Vigencies:
    """As vigências de um dono (sem pessoa nem grupo: a instalação), em ordem."""
    rows = await db.execute(
        select(
            WorkSchedule.valid_from,
            WorkSchedule.weekdays,
            WorkSchedule.start,
            WorkSchedule.end,
            WorkSchedule.break_start,
            WorkSchedule.break_end,
        )
        .where(*_owner(user_id, team_id))
        .order_by(WorkSchedule.valid_from.asc().nulls_first())
    )
    return [(row.valid_from or date.min, _schedule(row)) for row in rows]


def snapshot(schedule: Schedule | None) -> dict[str, Any] | None:
    """O expediente na auditoria (None: sem expediente próprio)."""
    if schedule is None:
        return None
    found: dict[str, Any] = {
        "weekdays": list(schedule.weekdays),
        "start": schedule.start.isoformat("minutes"),
        "end": schedule.end.isoformat("minutes"),
    }
    if schedule.break_start and schedule.break_end:
        found["break_start"] = schedule.break_start.isoformat("minutes")
        found["break_end"] = schedule.break_end.isoformat("minutes")
    return found


async def save_vigency(
    db: AsyncSession,
    valid_from: date,
    schedule: Schedule | None,
    *,
    user_id: int | None = None,
    team_id: int | None = None,
) -> tuple[Schedule | None, Schedule | None] | None:
    """Grava a vigência de um dono a partir de `valid_from`: a da mesma data é substituída, e
    uma igual à que vem antes não fica gravada (seria a mesma coisa). Devolve o que valia nesse
    dia e o que passa a valer, ou None se nada mudou. A instalação sempre tem um expediente."""
    found = await vigencies(db, user_id=user_id, team_id=team_id)
    # Sem vigência, a instalação tem o padrão; a pessoa e o grupo, nenhum (seguem o de cima).
    fallback = DEFAULT_SCHEDULE if user_id is None and team_id is None else None
    before = _at(found, valid_from) or fallback
    earlier = _at([v for v in found if v[0] < valid_from], valid_from) or fallback
    if schedule == before:
        return None
    existing = await db.scalar(
        select(WorkSchedule).where(*_owner(user_id, team_id), WorkSchedule.valid_from == valid_from)
    )
    if schedule == earlier:
        if existing is not None:
            await db.delete(existing)
    else:
        row = existing or WorkSchedule(user_id=user_id, team_id=team_id, valid_from=valid_from)
        row.weekdays = list(schedule.weekdays) if schedule else None
        row.start = schedule.start if schedule else None
        row.end = schedule.end if schedule else None
        row.break_start = schedule.break_start if schedule else None
        row.break_end = schedule.break_end if schedule else None
        db.add(row)
    await db.flush()
    return before, schedule


async def set_schedule(
    db: AsyncSession,
    request: Request | None,
    actor_user_id: int,
    owner: User | Team,
    valid_from: date,
    schedule: Schedule | None,
) -> bool:
    """A vigência de um grupo (quem tem admin.organization) ou de uma pessoa (admin.users), com
    a auditoria antes e depois; a da instalação é a `PUT /admin/settings/work-hours`. Devolve se
    mudou (o commit é de quem chama)."""
    kind = "user" if isinstance(owner, User) else "team"
    changed = await save_vigency(db, valid_from, schedule, **{f"{kind}_id": owner.id})
    if changed is None:
        return False
    record(
        db,
        f"{kind}.work_hours_set",
        request=request,
        actor_user_id=actor_user_id,
        target_type=kind,
        target_id=owner.public_id,
        before={"valid_from": valid_from.isoformat(), "work_hours": snapshot(changed[0])},
        after={"valid_from": valid_from.isoformat(), "work_hours": snapshot(changed[1])},
    )
    return True
