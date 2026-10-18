"""Lista de chamados com as filas (docs/10 §10.6, docs/13 §13.5) e o status em massa.

A aba e os filtros ficam na URL, para o link poder ser compartilhado. Os dados vêm das mesmas
funções da API (`tickets/router.py`); a permissão de cada chamado é conferida lá.
"""

import re
import uuid
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError

from chamados.core.i18n import translate as translate_api
from chamados.db.session import DB
from chamados.modules.catalog import router as catalog_api
from chamados.modules.organization import router as organization_api
from chamados.modules.tickets import router as tickets_api
from chamados.modules.tickets import service
from chamados.modules.tickets.schemas import BulkStatusIn, StatusKind, TicketView
from chamados.web.page import HOME, FlashKind, LoggedPageDep, Redirect, check_csrf, flash, safe_next

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
# Busca do cabeçalho (docs/13 §13.1): "1234" ou "#1234" abre o chamado.
NUMBER = re.compile(r"^#?(\d+)$")


def _uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
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
    q: str | None = None,
    cursor: str | None = None,
) -> HTMLResponse:
    q = (q or "").strip()[:200] or None
    if q and (number := NUMBER.match(q)):
        raise Redirect(f"/chamados/{number.group(1)}")
    auth = page.auth
    tab = aba if aba in TABS else ("meus" if auth.actor.teams else "todos")
    view = TABS[tab]
    team = _uuid(grupo)
    # Status e responsável só filtram a aba Todos; as outras já os definem.
    kind = next((k for k in KINDS if k == status), None) if view == "all" else None
    mine = view == "all" and responsavel == "eu"
    result = await tickets_api.list_tickets(
        auth,
        db,
        view=view,
        team=team,
        assignee="me" if mine else None,
        status=[kind] if kind else None,
        q=q,
        limit=50,
        cursor=cursor,
    )
    filters = {
        "aba": tab,
        "grupo": str(team) if team else None,
        "status": kind,
        "responsavel": "eu" if mine else None,
        "q": q,
    }
    query = {k: v for k, v in filters.items() if v}

    def url(**changes: str | None) -> str:
        params = {k: v for k, v in {**query, **changes}.items() if v}
        return f"/chamados?{urlencode(params)}"

    bulk = page.can("ticket.bulk")
    teams = (await organization_api.list_teams(auth, db)).items
    statuses = (await catalog_api.list_statuses(auth, db)).items if bulk else []
    return page.render(
        "tickets/list.html",
        tabs=TABS,
        tab=tab,
        view=view,
        filters=filters,
        url=url,
        # Trocar de aba mantém o grupo e a busca (status e responsável só existem em Todos).
        tab_url=lambda slug: url(aba=slug, status=None, responsavel=None),
        current_url=url(),
        tickets=result.items,
        next_cursor=result.next_cursor,
        counts=await tickets_api.ticket_counts(auth, db),
        team_options=[(str(t.id), t.name) for t in teams if t.is_active],
        kind_options=[(k, page.t(f"chamados.filtros.kinds.{k}")) for k in KINDS],
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
        return response
    try:
        updated, failed = await service.bulk_status(db, page.auth, data.numbers, data.status_id)
    except HTTPException as exc:  # status inexistente
        flash(response, ("error", page.api_message(exc)))
        return response
    messages: list[tuple[FlashKind, str]] = []
    if updated:
        messages.append(("success", page.t("chamados.alteradosEmMassa", n=len(updated))))
    if failed:
        items = "; ".join(f"#{n} ({translate_api(d, page.locale)})" for n, d in failed)
        messages.append(("error", page.t("chamados.naoMudaram", lista=items)))
    flash(response, *messages)
    return response
