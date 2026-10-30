"""O painel do papel Cliente (docs/14 §14.9): o plano da empresa e os chamados do mês, sem
filtros. Os chamados passam por `ticket_visibility_filter`, que para esse papel são todos os da
empresa dele (e nenhum outro)."""

from dataclasses import dataclass
from datetime import date, datetime, time

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from chamados.core.timezone import LOCAL_TZ
from chamados.modules.catalog.models import TicketStatus
from chamados.modules.clients.models import Client
from chamados.modules.identity.deps import Auth
from chamados.modules.reports.service import WITH_HOURS
from chamados.modules.tickets.models import Ticket, TicketComment
from chamados.modules.tickets.service import ACTIVE, time_spent
from chamados.modules.tickets.visibility import ticket_visibility_filter


@dataclass
class PanelTicket:
    number: int
    title: str
    status: TicketStatus
    minutes: int  # o total do chamado, de sempre


@dataclass
class ClientPanel:
    client: Client
    # O período das horas: o ano no contrato anual; o mês nos outros.
    yearly: bool
    plan: int | None  # minutos do plano; sem plano (avulso ou sem contrato), None
    worked: int
    tickets: list[PanelTicket]
    statuses: list[tuple[TicketStatus, int]]  # todos, na ordem das Configurações

    @property
    def excess(self) -> int:
        """Além do plano no período (o mesmo que a soma do `Plan.excess` das tarefas dele)."""
        return max(0, self.worked - self.plan) if self.plan is not None else 0


def _start(day: date) -> datetime:
    return datetime.combine(day, time(), LOCAL_TZ)


async def client_panel(db: AsyncSession, auth: Auth, today: date) -> ClientPanel:
    """O mês (ou o ano) de `today`. Os chamados: os registrados no mês, os que tiveram tarefa no
    mês e os que ainda estão em aberto, com o tempo total de cada um."""
    client = await db.get_one(Client, auth.actor.client_id)
    yearly = client.contract_type == "annual"
    plan = (
        client.contract_hours * 60
        if client.contract_type in WITH_HOURS and client.contract_hours
        else None
    )
    month = _start(today.replace(day=1))
    since = _start(today.replace(month=1, day=1)) if yearly else month
    visible = ticket_visibility_filter(auth.actor)
    worked = await db.scalar(
        select(func.coalesce(func.sum(TicketComment.time_spent_minutes), 0))
        .join(Ticket, Ticket.id == TicketComment.ticket_id)
        .where(visible, TicketComment.deleted_at.is_(None), TicketComment.done_at >= since)
    )
    worked_in_month = exists().where(
        TicketComment.ticket_id == Ticket.id,
        TicketComment.deleted_at.is_(None),
        TicketComment.done_at >= month,
    )
    rows = await db.execute(
        select(Ticket.number, Ticket.title, TicketStatus, time_spent().label("minutes"))
        .join(Ticket.status)
        .where(
            visible,
            or_(Ticket.created_at >= month, worked_in_month, TicketStatus.kind.in_(ACTIVE)),
        )
        .order_by(time_spent().desc(), Ticket.number.desc())
    )
    tickets = [PanelTicket(n, title, status, minutes) for n, title, status, minutes in rows]
    statuses = await db.scalars(select(TicketStatus).order_by(TicketStatus.sort_order))
    return ClientPanel(
        client=client,
        yearly=yearly,
        plan=plan,
        worked=worked or 0,
        tickets=tickets,
        statuses=[(s, sum(t.status.id == s.id for t in tickets)) for s in statuses],
    )
