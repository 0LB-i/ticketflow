import uuid
from datetime import date, datetime

from pydantic import BaseModel

from chamados.modules.system.work_hours import WorkHours


class Ref(BaseModel):
    id: uuid.UUID
    name: str


class ReportOptions(BaseModel):
    """O que a pessoa pode escolher nos filtros: só o que ela tem direito de ver."""

    teams: list[Ref]
    people: list[Ref]


class Totals(BaseModel):
    minutes: int
    overtime_minutes: int
    tasks: int
    tickets_opened: int
    tickets_closed: int


class PersonRow(BaseModel):
    id: uuid.UUID
    name: str
    minutes: int
    overtime_minutes: int
    tasks: int
    tickets_closed: int


class ClientRow(BaseModel):
    id: uuid.UUID | None  # nulo: chamados sem cliente
    name: str | None
    minutes: int
    tickets_opened: int
    tickets_closed: int


class DayRow(BaseModel):
    date: date
    minutes: int
    overtime_minutes: int


class OvertimeTask(BaseModel):
    ticket_number: int
    ticket_title: str
    person: str
    done_at: datetime
    minutes: int
    overtime_minutes: int


class Report(BaseModel):
    start: date
    end: date
    work_hours: WorkHours
    totals: Totals
    people: list[PersonRow]
    clients: list[ClientRow]
    days: list[DayRow]
    overtime_tasks: list[OvertimeTask]
