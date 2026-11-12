"""Agenda (/agenda): os compromissos da pessoa por mês, semana ou dia, como nos serviços de e-mail.

Novo e editar abrem numa janela no meio da tela (`?novo=1`, `?editar=<id>`); só o dono
altera, os demais participantes veem o compromisso só para leitura. O chamado é escolhido pela busca
(`/agenda/chamados`, só os que a pessoa vê). O aviso do menu (`/agenda/aviso`) conta os
compromissos que começam em até 15 minutos; abrir a agenda o apaga (`take_alerts`).
"""

import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from chamados.db.session import DB
from chamados.modules.appointments import service
from chamados.modules.appointments.models import Appointment
from chamados.modules.appointments.service import AppointmentData, LinkedTicket
from chamados.modules.organization import router as organization_api
from chamados.modules.tickets import service as tickets_service
from chamados.web.formatting import (
    TIMEZONE,
    format_date,
    format_day,
    format_month,
    local_parts,
    parse_local,
)
from chamados.web.page import LoggedPage, LoggedPageDep, PageDep, check_csrf
from chamados.web.ticket import _people

router = APIRouter()

URL = "/agenda"
VIEWS = ("mes", "semana", "dia")
# A grade de horas da semana e do dia mostra pelo menos este trecho; um compromisso fora dele a
# estica até a hora dele.
FIRST_HOUR, LAST_HOUR = 7, 19
# Na grade do mês, quantos compromissos cabem num dia; o resto vira "+N".
MONTH_ITEMS = 3

FormField = Annotated[str, Form()]


@dataclass
class Item:
    """Um compromisso num dia: o trecho dele naquele dia e o lugar na grade de horas."""

    appointment: Appointment
    ticket: LinkedTicket | None
    start: datetime
    end: datetime
    top: float = 0.0
    height: float = 0.0
    lane: int = 0
    lanes: int = 1


@dataclass
class Day:
    day: date
    in_month: bool
    today: bool
    all_day: list[Item] = field(default_factory=list)
    timed: list[Item] = field(default_factory=list)

    @property
    def items(self) -> list[Item]:
        return self.all_day + self.timed


@dataclass
class AppointmentForm:
    titulo: str = ""
    descricao: str = ""
    inicio_data: str = ""
    inicio_hora: str = "09:00"
    fim_data: str = ""
    fim_hora: str = "10:00"
    dia_inteiro: bool = False
    chamado: str = ""
    chamado_nome: str = ""
    participantes: list[str] = field(default_factory=list)

    @classmethod
    def starting(cls, start: datetime) -> "AppointmentForm":
        """Compromisso novo de uma hora a partir de `start` (local)."""
        end = start + timedelta(hours=1)
        return cls(
            inicio_data=start.date().isoformat(),
            inicio_hora=start.strftime("%H:%M"),
            fim_data=end.date().isoformat(),
            fim_hora=end.strftime("%H:%M"),
        )

    @classmethod
    def of(cls, a: Appointment, ticket: LinkedTicket | None) -> "AppointmentForm":
        start = local_parts(a.starts_at)
        # No dia inteiro, o fim gravado é a meia-noite seguinte: o campo mostra o último dia.
        end = local_parts(a.ends_at - timedelta(days=1) if a.all_day else a.ends_at)
        return cls(
            titulo=a.title,
            descricao=a.description or "",
            inicio_data=start[0],
            inicio_hora=start[1],
            fim_data=end[0],
            fim_hora=end[1],
            dia_inteiro=a.all_day,
            chamado=str(ticket.number) if ticket else "",
            chamado_nome=_ticket_label(ticket) if ticket else "",
            participantes=[str(x.user.public_id) for x in a.attendees if x.user_id != a.owner_id],
        )


def _ticket_label(ticket: LinkedTicket) -> str:
    return f"#{ticket.number} · {ticket.title}" if ticket.title else f"#{ticket.number}"


def _view(value: str | None) -> str:
    return value if value in VIEWS else "mes"


def _today() -> date:
    return datetime.now(TIMEZONE).date()


def _parse_day(value: str | None) -> date:
    try:
        return date.fromisoformat(value or "")
    except ValueError:
        return _today()


def _period(view: str, day: date) -> tuple[date, date]:
    """Primeiro e último dia mostrados. A semana começa no domingo, como o calendário dos campos
    de data (app.js); o mês ocupa semanas inteiras."""
    if view == "dia":
        return day, day
    if view == "semana":
        first = day - timedelta(days=(day.weekday() + 1) % 7)
        return first, first + timedelta(days=6)
    month_start = day.replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    first = month_start - timedelta(days=(month_start.weekday() + 1) % 7)
    last_of_month = next_month - timedelta(days=1)
    last = last_of_month + timedelta(days=(5 - last_of_month.weekday()) % 7)
    return first, last


def _shift(view: str, day: date, step: int) -> date:
    if view == "dia":
        return day + timedelta(days=step)
    if view == "semana":
        return day + timedelta(days=7 * step)
    month = day.month - 1 + step
    return date(day.year + month // 12, month % 12 + 1, 1)


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time(), TIMEZONE)


def _place(items: list[Item], first_hour: int, last_hour: int) -> None:
    """Posição de cada compromisso na grade (em % da altura) e as colunas dos que se sobrepõem:
    cada grupo de sobrepostos divide a largura pelo maior número de colunas que ele precisa."""
    span = (last_hour - first_hour) * 60
    group: list[Item] = []
    lane_ends: list[datetime] = []
    group_end: datetime | None = None
    for item in sorted(items, key=lambda i: (i.start, -(i.end - i.start).total_seconds())):
        day_start = _midnight(item.start.astimezone(TIMEZONE).date())
        minutes = (item.start - day_start).total_seconds() / 60 - first_hour * 60
        length = max((item.end - item.start).total_seconds() / 60, 15)
        item.top = max(minutes, 0) / span * 100
        item.height = min(length, span - max(minutes, 0)) / span * 100
        if group_end is not None and item.start >= group_end:
            for g in group:
                g.lanes = len(lane_ends)
            group, lane_ends = [], []
        lane = next((i for i, end in enumerate(lane_ends) if end <= item.start), len(lane_ends))
        if lane == len(lane_ends):
            lane_ends.append(item.end)
        else:
            lane_ends[lane] = item.end
        item.lane = lane
        group.append(item)
        group_end = item.end if group_end is None else max(group_end, item.end)
    for g in group:
        g.lanes = len(lane_ends)


def _days(
    appointments: list[Appointment],
    tickets: dict[int, LinkedTicket],
    first: date,
    last: date,
    month: int | None,
) -> list[Day]:
    today = _today()
    days = []
    day = first
    while day <= last:
        start, end = _midnight(day), _midnight(day + timedelta(days=1))
        d = Day(day, month is None or day.month == month, day == today)
        for a in appointments:
            if a.starts_at < end and a.ends_at > start:
                item = Item(
                    a,
                    tickets.get(a.ticket_id) if a.ticket_id else None,
                    max(a.starts_at, start).astimezone(TIMEZONE),
                    min(a.ends_at, end).astimezone(TIMEZONE),
                )
                (d.all_day if a.all_day else d.timed).append(item)
        days.append(d)
        day += timedelta(days=1)
    return days


def _hours(days: list[Day]) -> tuple[int, int]:
    """O trecho da grade: o padrão, esticado até o compromisso mais cedo e o mais tarde."""
    timed = [i for d in days for i in d.timed]
    first = min([FIRST_HOUR, *(i.start.hour for i in timed)])
    last = max(
        [
            LAST_HOUR,
            *(
                24 if i.end.date() > i.start.date() else math.ceil(i.end.hour + i.end.minute / 60)
                for i in timed
            ),
        ]
    )
    return first, last


def _url(view: str, day: date, **extra: str) -> str:
    return f"{URL}?{urlencode({'visao': view, 'data': day.isoformat(), **extra})}"


def _title(page: LoggedPage, view: str, first: date, last: date, day: date) -> str:
    if view == "mes":
        return format_month(page.locale, day)
    if view == "dia":
        weekday = page.t("agenda.diasSemana").split("|")[(day.weekday() + 1) % 7]
        return f"{weekday}, {format_date(page.locale, day)}"
    return f"{format_day(page.locale, first)} – {format_date(page.locale, last)}"


async def _agenda_page(
    page: LoggedPage,
    db: DB,
    *,
    view: str,
    day: date,
    novo: bool = False,
    inicio: str | None = None,
    editar: str | None = None,
    form: AppointmentForm | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    auth = page.auth
    now = datetime.now(UTC)
    # Abrir a agenda apaga o aviso; os compromissos dele aparecem no topo. Um trecho do HTMX
    # (abrir o painel) não conta: a página já estava aberta.
    alerts = (
        [] if page.request.headers.get("HX-Request") else await service.take_alerts(db, auth, now)
    )
    first, last = _period(view, day)
    appointments = await service.between(
        db, auth, _midnight(first), _midnight(last + timedelta(days=1))
    )
    edited = await service.get(db, auth, editar) if editar else None
    tickets = await service.linked_tickets(
        db, auth, [*appointments, *alerts, *filter(None, [edited])]
    )
    days = _days(appointments, tickets, first, last, day.month if view == "mes" else None)
    hours = _hours(days)
    for d in days:
        _place(d.timed, *hours)

    if form is None and edited is not None:
        form = AppointmentForm.of(
            edited, tickets.get(edited.ticket_id) if edited.ticket_id else None
        )
    elif form is None and novo:
        start = None
        if inicio:
            date_part, _, time_part = inicio.partition("T")
            start = parse_local(date_part, time_part or "09:00")
        form = AppointmentForm.starting(start or _midnight(day) + timedelta(hours=9))

    teams = (await organization_api.list_teams(auth, db)).items
    me = str(auth.user.public_id)
    people = [p for p in _people(teams) if p[0] != me]
    names = dict(people)
    if edited is not None:
        names |= {str(x.user.public_id): x.user.display_name for x in edited.attendees}
    return page.render(
        "agenda/index.html",
        status_code=status_code,
        view=view,
        day=day,
        title=_title(page, view, first, last, day),
        days=days,
        weeks=[days[i : i + 7] for i in range(0, len(days), 7)],
        hours=range(*hours),
        month_items=MONTH_ITEMS,
        alerts=[(a, tickets.get(a.ticket_id) if a.ticket_id else None) for a in alerts],
        back=_url(view, day),
        url=_url,
        today=_today(),
        prev_day=_shift(view, day, -1),
        next_day=_shift(view, day, 1),
        edited=edited,
        creating=edited is None and form is not None,
        own=edited is None or edited.owner_id == auth.user.id,
        form=form,
        error=error,
        people=people,
        names=names,
        weekdays=page.t("agenda.diasSemana").split("|"),
        local=lambda value: value.astimezone(TIMEZONE),
    )


@router.get(URL)
async def agenda_page(
    page: LoggedPageDep,
    db: DB,
    visao: str = "mes",
    data: str | None = None,
    novo: bool = False,
    inicio: str | None = None,
    editar: str | None = None,
) -> HTMLResponse:
    return await _agenda_page(
        page,
        db,
        view=_view(visao),
        day=_parse_day(data),
        novo=novo,
        inicio=inicio,
        editar=editar,
    )


@router.get(URL + "/aviso")
async def alert_badge(page: PageDep, db: DB) -> Response:
    """A bolinha do menu, perguntada a cada minuto. Sem sessão, não leva ao login (a pessoa
    perderia o que está escrevendo em outra tela): o 286 faz o HTMX parar de perguntar."""
    if page.auth is None or page.auth.user.must_change_password or page.is_client:
        return Response(status_code=286, headers={"HX-Reswap": "none"})
    count = await service.alert_count(db, page.auth, datetime.now(UTC))
    return page.render("agenda/_alert.html", count=count)


@router.get(URL + "/chamados")
async def ticket_options(page: LoggedPageDep, db: DB, q: str = "") -> HTMLResponse:
    """Opções do campo de chamado (HTMX): pelo número ou pelo texto, só os que a pessoa vê."""
    rows, _ = await tickets_service.list_tickets(
        db,
        page.auth,
        view="all",
        team=None,
        assignee=None,
        kinds=(),
        q=q.strip()[:200] or None,
        limit=20,
        cursor=None,
    )
    return page.render("agenda/_ticket_options.html", tickets=[t for t, _, _ in rows])


def _data(form: AppointmentForm) -> AppointmentData:
    """O formulário no que o service recebe; data ou hora inválida é ValueError."""
    if form.dia_inteiro:
        starts_at, ends_at = service.all_day_period(
            date.fromisoformat(form.inicio_data), date.fromisoformat(form.fim_data)
        )
    else:
        start = parse_local(form.inicio_data, form.inicio_hora)
        end = parse_local(form.fim_data, form.fim_hora)
        if start is None or end is None:
            raise ValueError
        starts_at, ends_at = start, end
    return AppointmentData(
        title=form.titulo,
        description=form.descricao,
        starts_at=starts_at,
        ends_at=ends_at,
        all_day=form.dia_inteiro,
        ticket_number=int(form.chamado) if form.chamado else None,
        attendee_ids=[uuid.UUID(p) for p in form.participantes],
    )


def _posted_form(
    titulo: FormField = "",
    descricao: FormField = "",
    inicio_data: FormField = "",
    inicio_hora: FormField = "",
    fim_data: FormField = "",
    fim_hora: FormField = "",
    dia_inteiro: FormField = "",
    chamado: FormField = "",
    chamado_nome: FormField = "",
    participantes: Annotated[list[str] | None, Form()] = None,
) -> AppointmentForm:
    number = chamado.strip().lstrip("#")
    return AppointmentForm(
        titulo=titulo,
        descricao=descricao,
        inicio_data=inicio_data,
        inicio_hora=inicio_hora,
        fim_data=fim_data or inicio_data,
        fim_hora=fim_hora,
        dia_inteiro=dia_inteiro == "1",
        chamado=number if number.isascii() and number.isdigit() else "",
        chamado_nome=chamado_nome if number else "",
        participantes=list(dict.fromkeys(participantes or [])),
    )


PostedForm = Annotated[AppointmentForm, Depends(_posted_form)]


async def _save(
    page: LoggedPage, db: DB, form: AppointmentForm, view: str, day: date, editar: str | None
) -> Response:
    """Grava e volta para a agenda; erro devolve a página com a janela aberta e o que foi
    digitado. O service confere tudo antes de mudar o compromisso: nada a desfazer."""
    appointment = await service.get(db, page.auth, editar) if editar else None
    try:
        await service.save(db, page.auth, _data(form), appointment)
    except ValueError:
        error = page.t("dataHora.invalida")
    except HTTPException as exc:
        error = page.api_message(exc)
    else:
        response = RedirectResponse(_url(view, day), status_code=303)
        page.flash(response, ("success", page.t("agenda.salvo")))
        return response
    return await _agenda_page(
        page, db, view=view, day=day, editar=editar, form=form, error=error, status_code=422
    )


@router.post(URL + "/novo")
async def create_appointment(
    page: LoggedPageDep,
    db: DB,
    form: PostedForm,
    csrf_token: FormField = "",
    visao: FormField = "mes",
    data: FormField = "",
) -> Response:
    check_csrf(page, csrf_token)
    return await _save(page, db, form, _view(visao), _parse_day(data), None)


@router.post(URL + "/{appointment_id}")
async def edit_appointment(
    appointment_id: str,
    page: LoggedPageDep,
    db: DB,
    form: PostedForm,
    csrf_token: FormField = "",
    visao: FormField = "mes",
    data: FormField = "",
) -> Response:
    check_csrf(page, csrf_token)
    return await _save(page, db, form, _view(visao), _parse_day(data), appointment_id)


@router.post(URL + "/{appointment_id}/remover")
async def remove_appointment(
    appointment_id: str,
    page: LoggedPageDep,
    db: DB,
    csrf_token: FormField = "",
    visao: FormField = "mes",
    data: FormField = "",
) -> Response:
    check_csrf(page, csrf_token)
    appointment = await service.get(db, page.auth, appointment_id)
    response = RedirectResponse(_url(_view(visao), _parse_day(data)), status_code=303)
    try:
        await service.remove(db, page.auth, appointment)
    except HTTPException as exc:
        page.flash(response, ("error", page.api_message(exc)))
    else:
        page.flash(response, ("success", page.t("agenda.removido")))
    return response
