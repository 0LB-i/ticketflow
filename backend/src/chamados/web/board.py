"""Quadro (kanban) dos chamados: uma coluna por status, e arrastar um cartão muda o status.

Cada pessoa vê os chamados de que é responsável; o supervisor também os dos grupos que
supervisiona, e pode filtrar por responsável. A mudança é o mesmo formulário de status do
detalhe (`POST /chamados/{n}/status`, com o ETag), que volta para o quadro. No mês passado,
o topo tem as datas de conclusão e de cancelamento que os cartões soltos nessas colunas levam,
para os relatórios contarem o chamado no mês certo.
"""

from datetime import date, datetime, timedelta
from typing import NamedTuple
from urllib.parse import urlencode

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from chamados.db.session import DB
from chamados.modules.catalog import router as catalog_api
from chamados.modules.catalog.router import StatusOption
from chamados.modules.clients.models import Client
from chamados.modules.tickets import service
from chamados.modules.tickets.models import Ticket
from chamados.web.formatting import TIMEZONE, local_parts
from chamados.web.page import LoggedPageDep

router = APIRouter()


class Card(NamedTuple):
    ticket: Ticket
    has_news: bool
    etag: str
    client: str
    # Status para onde a pessoa pode mover o chamado (vazio: o cartão não se move).
    targets: list[StatusOption]


def _client_name(client: Client | None) -> str:
    """Empresa pelo nome fantasia, que costuma ser o conhecido (a razão social pode ser bem
    diferente); sem ele, e para pessoa física, o nome das outras telas."""
    if client is None:
        return "—"
    if client.kind == "company" and client.trade_name:
        return client.trade_name
    return client.label


def _month(previous: bool) -> tuple[datetime, datetime]:
    """Início do mês (o atual ou o passado) e do seguinte, no horário da máquina."""
    start = datetime.now(TIMEZONE).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if previous:
        return (start - timedelta(days=1)).replace(day=1), start
    return start, (start + timedelta(days=32)).replace(day=1)


def _day_in(value: str | None, first: str, last: str) -> str:
    """A data escolhida ("2026-09-15"), se for do mês; senão, o último dia dele."""
    try:
        day = date.fromisoformat(value or "").isoformat()
    except ValueError:
        return last
    return day if first <= day <= last else last


@router.get("/quadro")
async def board_page(
    page: LoggedPageDep,
    db: DB,
    responsavel: str | None = None,
    mes: str | None = None,
    concluir_em: str | None = None,
    cancelar_em: str | None = None,
) -> HTMLResponse:
    auth = page.auth
    previous = mes == "passado"
    # Concluídos e cancelados: do mês atual ou do passado.
    month = _month(previous)
    rows, truncated = await service.board(db, auth, month=month)
    # Na ordem das Configurações, com os cancelados por último.
    statuses = sorted(await catalog_api.status_options(db), key=lambda s: s.kind == "canceled")

    # Filtro por responsável (principal ou um dos outros), entre os que estão no quadro.
    people: dict[str, str] = {}
    for t, _ in rows:
        for user in (t.assignee, *(c.user for c in t.co_assignees)):
            people[str(user.public_id)] = user.display_name
    if responsavel in people:
        rows = [
            (t, news)
            for t, news in rows
            if responsavel
            in {str(t.assignee.public_id), *(str(c.user.public_id) for c in t.co_assignees)}
        ]
    else:
        responsavel = None

    columns: dict[int, list[Card]] = {s.id: [] for s in statuses}
    for t, news in rows:
        actions = service.actions(auth, t)
        # Como no detalhe: qualquer status, e os concluídos só com set_status_closed.
        targets = [
            s
            for s in statuses
            if "set_status" in actions
            and s.id != t.status_id
            and (s.kind != "closed" or "set_status_closed" in actions)
        ]
        columns[t.status_id].append(Card(t, news, service.etag(t), _client_name(t.client), targets))

    supervisor = auth.actor.role == "admin" or bool(auth.actor.supervises)
    # No mês passado: os dias dele e as datas de conclusão e de cancelamento (o último, de início).
    first, last = local_parts(month[0])[0], local_parts(month[1] - timedelta(days=1))[0]
    filters = {
        "responsavel": responsavel,
        "mes": "passado" if previous else None,
        "concluir_em": _day_in(concluir_em, first, last) if previous else None,
        "cancelar_em": _day_in(cancelar_em, first, last) if previous else None,
    }
    query = {k: v for k, v in filters.items() if v}
    return page.render(
        "board/index.html",
        columns=[(s, columns[s.id]) for s in statuses],
        truncated=truncated,
        limit=service.BOARD_LIMIT,
        filters=filters,
        # Só o supervisor (e o admin) vê o quadro de outras pessoas.
        people=sorted(people.items(), key=lambda p: p[1]) if supervisor else [],
        current_url=f"/quadro?{urlencode(query)}" if query else "/quadro",
        month_dates=(first, last),
    )
