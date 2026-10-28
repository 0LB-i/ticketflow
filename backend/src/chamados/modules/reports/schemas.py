import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from chamados.modules.system.work_hours import Schedule, WorkHours


class Ref(BaseModel):
    id: uuid.UUID
    name: str


class StatusRef(BaseModel):
    id: int
    name: str


class ReportOptions(BaseModel):
    """O que a pessoa pode escolher nos filtros: grupo e pessoa, só o que ela tem direito de ver."""

    teams: list[Ref]
    people: list[Ref]
    clients: list[Ref]  # ativos e inativos: um chamado antigo pode ser de um cliente inativado
    statuses: list[StatusRef]


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
    # O plano do contrato (mensal ou anual, `service.plan_usage`): `minutes` = no plano +
    # excedentes. Sem plano (avulso, sem contrato, sem cliente), todos os minutos são excedentes.
    in_plan_minutes: int
    excess_minutes: int


class DayRow(BaseModel):
    date: date
    minutes: int
    overtime_minutes: int


class TaskRow(BaseModel):
    ticket_number: int
    ticket_title: str
    client: str | None  # nulo: chamado sem cliente
    person: str
    done_at: datetime
    minutes: int
    overtime_minutes: int
    # O expediente de quem fez a tarefa, no dia em que ela terminou: só para o CSV (fora da API).
    schedule: Schedule | None = Field(default=None, exclude=True)


class Report(BaseModel):
    start: date
    end: date
    work_hours: WorkHours
    totals: Totals
    people: list[PersonRow]
    clients: list[ClientRow]
    days: list[DayRow]
    overtime_tasks: list[TaskRow]
    # Todas as tarefas do período, só para o CSV (`build(..., all_tasks=True)`); fora da API.
    tasks: list[TaskRow] = Field(default=[], exclude=True)
