"""Lista de chamados com as filas (docs/10 §10.6, docs/13 §13.5) e o status em massa.

A aba e os filtros ficam na URL, para o link poder ser compartilhado. Os dados vêm das mesmas
funções da API (`tickets/router.py`); a permissão de cada chamado é conferida lá.
"""

import re
import uuid
from datetime import date, datetime, time, timedelta
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError

from chamados.core.i18n import translate as translate_api
from chamados.core.timezone import LOCAL_TZ
from chamados.db.session import DB
from chamados.modules.catalog import router as catalog_api
from chamados.modules.organization import router as organization_api
from chamados.modules.reports.service import client_labels
from chamados.modules.system.router import get_ticket_list
from chamados.modules.tickets import queries, service
from chamados.modules.tickets import router as tickets_api
from chamados.modules.tickets.schemas import BulkStatusIn, StatusKind, TicketView
from chamados.web.page import HOME, FlashKind, LoggedPageDep, Redirect, check_csrf, safe_next
from chamados.web.reports_state import NO_CLIENT, Values, parse_uuids

router = APIRouter()

# Slug da aba na URL → fila da API. Quem não está em nenhum grupo (admin, auditor) não tem
# filas: começa em Todos.
TABS: dict[str, TicketView] = {
    "meus": "mine",
    "aguardando": "waiting",
    "acompanhando": "watching",
    "todos": "all",
}
KINDS: tuple[StatusKind, ...] = ("open", "waiting", "delivered", "closed", "canceled")
ACTIVE_KINDS: tuple[StatusKind, ...] = ("open", "waiting", "delivered")
# Os status que cada fila mostra (service.view_filter): as opções do filtro de status.
TAB_KINDS: dict[TicketView, tuple[StatusKind, ...]] = {
    "mine": ACTIVE_KINDS,
    "waiting": ("waiting", "delivered"),
    "watching": ACTIVE_KINDS,
    "all": KINDS,
}
ALL_KINDS = "todos"  # o status da aba Todos que mostra também os encerrados e os cancelados
# Limite do status em massa (BulkStatusIn) e quantas falhas o aviso lista: o resto vira
# "e mais N", para o cookie do aviso não passar de 4 KB.
BULK_MAX = 200
FAILURES_SHOWN = 10
# Colunas que ordenam a lista (o cabeçalho): `?ordem=titulo` de A a Z, `?ordem=-titulo` de Z a A;
# sem `ordem`, a padrão (o mais novo primeiro).
SORTS: dict[str, str] = {
    "titulo": "title",
    "cliente": "client",
    "responsavel": "assignee",
    "grupo": "team",
    "inicio": "started",
    "movimentacao": "updated",
    "horas": "time",
}
# Busca do cabeçalho (docs/13 §13.1): "1234" ou "#1234" abre o chamado.
NUMBER = re.compile(r"^#?(\d+)$")
# Páginas vizinhas da atual que a paginação mostra; as outras viram "…" (a primeira e a última
# aparecem sempre).
NEIGHBORS = 2


def _uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


def _page_numbers(current: int, pages: int) -> list[int | None]:
    """Os números da paginação, com None no lugar das páginas puladas: 1 … 4 5 6 7 8 … 20. Uma
    página só não vira "…": aparece o número dela."""
    shown = sorted(
        {1, pages, *range(max(1, current - NEIGHBORS), min(pages, current + NEIGHBORS) + 1)}
    )
    numbers: list[int | None] = []
    previous = 0
    for n in shown:
        if n - previous == 2:
            numbers.append(n - 1)
        elif previous and n - previous > 2:
            numbers.append(None)
        numbers.append(n)
        previous = n
    return numbers


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


@router.get("/")
async def home() -> RedirectResponse:
    return RedirectResponse(HOME, status_code=303)


@router.get("/chamados")
async def tickets_page(
    page: LoggedPageDep,
    db: DB,
    aba: str | None = None,
    grupo: str | None = None,
    status: str | None = None,
    responsavel: str | None = None,
    cliente: Values = None,
    de: str | None = None,
    ate: str | None = None,
    q: str | None = None,
    ordem: str | None = None,
    pagina: int = 1,
) -> HTMLResponse:
    q = (q or "").strip()[:200] or None
    if q and (number := NUMBER.match(q)):
        raise Redirect(f"/chamados/{number.group(1)}")
    auth = page.auth
    tab = aba if aba in TABS else ("meus" if auth.actor.teams else "todos")
    view = TABS[tab]
    team = _uuid(grupo)
    # Status: os da fila e, para o admin, também os concluídos e os cancelados (a fila continua a
    # dos seus chamados, service.list_tickets). Na aba Todos, sem escolha, só os em andamento;
    # "todos" tira o filtro.
    tab_kinds = TAB_KINDS[view]
    if auth.actor.role == "admin":
        tab_kinds += tuple(k for k in ("closed", "canceled") if k not in tab_kinds)
    kind = status if status in tab_kinds else None
    if kind:
        kinds = [kind]
    elif view == "all" and status != ALL_KINDS:
        kinds = list(ACTIVE_KINDS)
    else:
        kinds = []
    # Responsável: a aba Meus já é a dos chamados da pessoa.
    mine = view != "mine" and responsavel == "eu"
    clients = parse_uuids(cliente)
    no_client = NO_CLIENT in (cliente or [])
    sort = (ordem or "").removeprefix("-")
    if sort not in SORTS:
        sort, ordem = "", None
    descending = bool(ordem and ordem.startswith("-"))
    start, end = _date(de), _date(ate)
    period_error = bool(start and end and start > end)
    started_from = started_before = None
    if not period_error:
        if start:
            started_from = datetime.combine(start, time(), LOCAL_TZ)
        if end:
            started_before = datetime.combine(end + timedelta(days=1), time(), LOCAL_TZ)
    filtering: dict[str, Any] = dict(
        view=view,
        team=team,
        assignee="me" if mine else None,
        kinds=kinds,
        q=q,
        clients=clients,
        no_client=no_client,
        started_from=started_from,
        started_before=started_before,
    )
    # Páginas numeradas: fora do intervalo, a mais próxima. "Todos" nas Configurações (nulo): uma
    # página com o total.
    total = await service.count_tickets(db, auth, **filtering)
    per_page = (await get_ticket_list(db)).page_size or max(total, 1)
    pages = max(1, -(-total // per_page))
    current = min(max(pagina, 1), pages)
    result = await queries.list_page(
        db,
        auth,
        **filtering,
        limit=per_page,
        cursor=None,
        sort=SORTS[sort] if sort else None,
        descending=descending,
        offset=(current - 1) * per_page,
    )
    client_names = {
        NO_CLIENT: page.t("relatorios.semCliente"),
        **{str(c): name for c, name in (await client_labels(db, clients)).items()},
    }
    chosen_clients = [str(c) for c in clients] + ([NO_CLIENT] if no_client else [])
    filters: dict[str, str | list[str] | None] = {
        "aba": tab,
        "grupo": str(team) if team else None,
        "status": kind or (ALL_KINDS if view == "all" and status == ALL_KINDS else None),
        "responsavel": "eu" if mine else None,
        "cliente": chosen_clients,
        "de": start.isoformat() if start else None,
        "ate": end.isoformat() if end else None,
        "q": q,
        "ordem": ordem,
    }
    query = {k: v for k, v in filters.items() if v}

    def url(**changes: str | None) -> str:
        params = {k: v for k, v in {**query, **changes}.items() if v}
        return f"/chamados?{urlencode(params, doseq=True)}"

    def page_url(n: int) -> str:
        return url(pagina=str(n) if n > 1 else None)

    def sort_url(column: str) -> str:
        """O próximo clique no cabeçalho: de A a Z, de Z a A e de volta à ordem padrão."""
        if sort != column:
            return url(ordem=column)
        return url(ordem=None if descending else f"-{column}")

    if view == "all":
        status_choices = [("", page.t("chamados.filtros.emAndamento"))]
        status_choices.append((ALL_KINDS, page.t("chamados.filtros.todos")))
    else:
        status_choices = [("", page.t("chamados.filtros.todos"))]
    status_choices += [(k, page.t(f"chamados.filtros.kinds.{k}")) for k in tab_kinds]
    bulk = page.can("ticket.bulk")
    teams = (await organization_api.list_teams(auth, db)).items
    statuses = await catalog_api.status_options(db) if bulk else []
    return page.render(
        "tickets/list.html",
        tabs=TABS,
        tab=tab,
        view=view,
        filters=filters,
        url=url,
        sort_url=sort_url,
        sort=sort,
        descending=descending,
        # Trocar de aba mantém os outros filtros; status e responsável mudam de sentido por aba.
        tab_url=lambda slug: url(aba=slug, status=None, responsavel=None),
        current_url=page_url(current),  # a volta do status em massa: a mesma página
        tickets=result.items,
        total=total,
        current_page=current,
        pages=pages,
        page_numbers=_page_numbers(current, pages),
        page_url=page_url,
        first_shown=(current - 1) * per_page + 1,
        last_shown=(current - 1) * per_page + len(result.items),
        counts=await tickets_api.ticket_counts(auth, db),
        team_options=[(str(t.id), t.name) for t in teams if t.is_active],
        kind_options=status_choices,
        client_names=client_names,
        period_error=period_error,
        bulk=bulk,
        status_options=[(s.id, s.name) for s in statuses],
    )


@router.post("/chamados/status-em-massa")
async def bulk_status(
    page: LoggedPageDep,
    db: DB,
    numeros: Annotated[list[int] | None, Form()] = None,
    status_id: Annotated[int | None, Form()] = None,
    csrf_token: Annotated[str, Form()] = "",
    volta: Annotated[str, Form()] = HOME,
) -> RedirectResponse:
    """Supervisor (nos grupos que supervisiona) ou admin. O service confere cada chamado e
    devolve os que não mudaram, com o motivo."""
    check_csrf(page, csrf_token)
    response = RedirectResponse(safe_next(volta), status_code=303)
    try:
        data = BulkStatusIn.model_validate({"numbers": numeros or [], "status_id": status_id})
    except ValidationError:
        if len(numeros or []) > BULK_MAX:
            page.flash(response, ("error", page.t("chamados.demaisParaMudar", n=BULK_MAX)))
        return response
    try:
        updated, failed = await service.bulk_status(db, page.auth, data.numbers, data.status_id)
    except HTTPException as exc:  # status inexistente
        page.flash(response, ("error", page.api_message(exc)))
        return response
    messages: list[tuple[FlashKind, str]] = []
    if updated:
        messages.append(("success", page.t("chamados.alteradosEmMassa", n=len(updated))))
    if failed:
        items = "; ".join(
            f"#{n} ({translate_api(d, page.locale)})" for n, d in failed[:FAILURES_SHOWN]
        )
        if len(failed) > FAILURES_SHOWN:
            items += " " + page.t("chamados.eMais", n=len(failed) - FAILURES_SHOWN)
        messages.append(("error", page.t("chamados.naoMudaram", lista=items)))
    page.flash(response, *messages)
    return response
