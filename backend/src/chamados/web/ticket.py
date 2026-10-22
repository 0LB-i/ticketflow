"""Registro (docs/10 §10.4) e detalhe do chamado (docs/10 §10.6), com as ações da lateral e as
tarefas. O que aparece depende de `allowed_actions`; cada ação passa pela mesma função da API
(`tickets/router.py`), que confere a permissão.
"""

import re
import unicodedata
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select

from chamados.db.session import DB
from chamados.modules.attachments.models import Attachment
from chamados.modules.catalog import router as catalog_api
from chamados.modules.clients import router as clients_api
from chamados.modules.organization import router as organization_api
from chamados.modules.organization.router import TeamOut
from chamados.modules.tickets import router as tickets_api
from chamados.modules.tickets import service as tickets_service
from chamados.modules.tickets.schemas import (
    AssigneesIn,
    AssignIn,
    CommentIn,
    TicketCreate,
    TicketOut,
    TicketUpdate,
    TransferIn,
    TransitionIn,
)
from chamados.web.formatting import (
    SUGGESTED_TIMES,
    local_parts,
    parse_duration,
    parse_local,
)
from chamados.web.page import LoggedPage, LoggedPageDep, check_csrf

router = APIRouter()

Field = Annotated[str, Form()]
Ids = Annotated[list[str] | None, Form()]
# Imagens coladas no editor: o texto guarda o endereço do anexo (como o anexos.ts da SPA).
ATTACHMENT_IN_TEXT = re.compile(
    r"/api/v1/attachments/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
)


# Ids vindos de formulário: um valor inválido vira ValidationError, tratado como os demais.
UUID = TypeAdapter(uuid.UUID)


def attachments_in_text(text: str) -> list[str]:
    return list(dict.fromkeys(ATTACHMENT_IN_TEXT.findall(text)))


def _sort_key(name: str) -> str:
    """Ordem alfabética sem diferença de acentos e maiúsculas."""
    return "".join(c for c in unicodedata.normalize("NFD", name) if not unicodedata.combining(c))


def _people(teams: list[TeamOut]) -> list[tuple[str, str]]:
    """Colegas ativos de todos os grupos (menções, observadores), em ordem alfabética."""
    seen: dict[str, str] = {}
    for team in teams:
        for m in team.members:
            if m.is_active:
                seen[str(m.user_id)] = m.display_name
    return sorted(seen.items(), key=lambda p: _sort_key(p[1]).casefold())


def _members(teams: list[TeamOut], team_id: str) -> list[tuple[str, str]]:
    team = next((t for t in teams if str(t.id) == team_id), None)
    return [(str(m.user_id), m.display_name) for m in team.members if m.is_active] if team else []


@dataclass
class DateTimeInput:
    """Campo de data e hora (`_ui.html`: datetime_field). Sem ajuste, acompanha a hora atual."""

    date: str
    time: str
    adjusted: bool = False

    @classmethod
    def now(cls) -> "DateTimeInput":
        return cls(*local_parts(datetime.now(UTC)))

    @classmethod
    def at(cls, value: datetime) -> "DateTimeInput":
        return cls(*local_parts(value), adjusted=True)

    @classmethod
    def from_form(cls, date: str, time: str, adjusted: str) -> "DateTimeInput":
        return cls(date, time, adjusted == "1") if adjusted == "1" else cls.now()

    @property
    def invalid(self) -> bool:
        """Ajustado à mão, mas com a data ou a hora apagada ou inválida."""
        return self.adjusted and parse_local(self.date, self.time) is None

    def value(self) -> datetime | None:
        """None: a hora atual (a API usa a do registro)."""
        return parse_local(self.date, self.time) if self.adjusted else None


async def _pending_attachments(page: LoggedPage, db: DB, ids: list[str]) -> list[Attachment]:
    """Envios ainda não vinculados de quem está na tela: voltam à lista se o formulário tiver
    erro (o arquivo já subiu na primeira etapa, docs/11 §11.4)."""
    valid = [i for i in ids if re.fullmatch(r"[0-9a-f-]{36}", i)]
    if not valid:
        return []
    rows = await db.scalars(
        select(Attachment).where(
            Attachment.public_id.in_(valid),
            Attachment.uploaded_by == page.auth.user.id,
            Attachment.ticket_id.is_(None),
        )
    )
    return list(rows)


async def _uploads_in_text(page: LoggedPage, db: DB, text: str) -> list[str]:
    """Imagens do texto que ainda são envios da pessoa: só elas vão para `attachment_ids`. Uma
    imagem citada (copiada da descrição ou de outra tarefa) já está vinculada e só fica no texto;
    mandá-la de novo seria "anexo já usado"."""
    pending = await _pending_attachments(page, db, attachments_in_text(text))
    return [str(a.public_id) for a in pending]


# --- registro ------------------------------------------------------------------------------


@dataclass
class NewTicketForm:
    team: str = ""
    status: str = ""
    title: str = ""
    description: str = ""
    started: DateTimeInput = field(default_factory=DateTimeInput.now)
    client_id: str = ""
    client_name: str = ""
    contact: str = ""
    assignees: list[str] = field(default_factory=list)
    watchers: list[str] = field(default_factory=list)
    attachments: list[str] = field(default_factory=list)


async def _new_ticket_page(
    page: LoggedPage,
    db: DB,
    form: NewTicketForm,
    errors: dict[str, str] | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    auth = page.auth
    teams = (await organization_api.list_teams(auth, db)).items
    team_options = [(str(t.id), t.name) for t in _registrable(page, teams)]
    statuses = await catalog_api.status_options(db)
    if not form.status:
        form.status = str(next((s.id for s in statuses if s.kind == "open"), ""))
    people = _people(teams)
    names = dict(people)
    members = _members(teams, form.team)
    return page.render(
        "tickets/new.html",
        status_code=status_code,
        form=form,
        errors=errors or {},
        error=error,
        team_options=team_options,
        members=members,
        names={**names, **dict(members)},
        can_choose_status=page.can("ticket.transition"),
        status_options=[(str(s.id), s.name) for s in statuses],
        watcher_options=[p for p in people if p[0] != str(auth.user.public_id)],
        people=[{"id": i, "label": n} for i, n in people],
        pending=await _pending_attachments(page, db, form.attachments),
        suggested_times=SUGGESTED_TIMES,
    )


def _my_team_ids(page: LoggedPage, teams: list[TeamOut]) -> set[Any]:
    me = page.auth.user.public_id
    return {t.id for t in teams if any(m.user_id == me for m in t.members)}


def _registrable(page: LoggedPage, teams: list[TeamOut]) -> list[TeamOut]:
    """Grupos ativos em que a pessoa registra: os próprios; com ticket.view_all (admin), qualquer
    um. O auditor também vê todos, mas não registra."""
    mine = _my_team_ids(page, teams)
    view_all = page.can("ticket.create") and page.can("ticket.view_all")
    return [t for t in teams if t.is_active and (view_all or t.id in mine)]


@router.get("/chamados/novo")
async def new_ticket_page(page: LoggedPageDep, db: DB, grupo: str = "") -> HTMLResponse:
    teams = (await organization_api.list_teams(page.auth, db)).items
    available = [str(t.id) for t in _registrable(page, teams)]
    # Com um grupo só, ele já vem escolhido; trocar de grupo recomeça a lista de responsáveis.
    team = grupo if grupo in available else (available[0] if len(available) == 1 else "")
    # Quem registra começa como responsável, menos fora dos próprios grupos (só membros ativos
    # do grupo podem ser responsáveis).
    mine = {str(i) for i in _my_team_ids(page, teams)}
    me = str(page.auth.user.public_id)
    form = NewTicketForm(team=team, assignees=[me] if team in mine else [])
    return await _new_ticket_page(page, db, form)


@router.post("/chamados/novo")
async def create_ticket(
    page: LoggedPageDep,
    db: DB,
    csrf_token: Field = "",
    grupo: Field = "",
    status_id: Field = "",
    titulo: Field = "",
    descricao: Field = "",
    inicio_data: Field = "",
    inicio_hora: Field = "",
    inicio_ajustado: Field = "",
    client_id: Field = "",
    cliente_nome: Field = "",
    contato: Field = "",
    responsaveis: Ids = None,
    observadores: Ids = None,
    attachment_ids: Ids = None,
    mention_ids: Ids = None,
) -> Response:
    check_csrf(page, csrf_token)
    form = NewTicketForm(
        team=grupo,
        status=status_id,
        title=titulo,
        description=descricao,
        started=DateTimeInput.from_form(inicio_data, inicio_hora, inicio_ajustado),
        client_id=client_id,
        client_name=cliente_nome,
        contact=contato,
        assignees=list(dict.fromkeys(responsaveis or [])),
        watchers=list(dict.fromkeys(observadores or [])),
        attachments=attachment_ids or [],
    )
    started = form.started.value()
    errors = {
        k: v
        for k, v in {
            "team": "novoChamado.escolhaGrupo" if not form.team else "",
            "title": "novoChamado.tituloCurto" if len(titulo.strip()) < 3 else "",
            "assignees": "novoChamado.escolhaResponsavel" if not form.assignees else "",
            "client": "novoChamado.escolhaCliente" if not client_id else "",
            # A API aceita até 5 minutos adiantado (relógio do computador); aqui, qualquer futuro.
            "started": "dataHora.invalida"
            if form.started.invalid
            else "novoChamado.inicioNoFuturo"
            if started and started > datetime.now(UTC)
            else "",
        }.items()
        if v
    }
    if errors:
        return await _new_ticket_page(page, db, form, errors=errors, status_code=422)

    # A API guarda um responsável principal (quem registra, se estiver na lista) e os demais.
    me = str(page.auth.user.public_id)
    main = me if me in form.assignees else form.assignees[0]
    try:
        data = TicketCreate.model_validate(
            {
                "title": titulo,
                "description": descricao,
                "team_id": form.team,
                "status_id": int(status_id)
                if page.can("ticket.transition") and status_id.isascii() and status_id.isdigit()
                else None,
                "started_at": started,
                "client_id": client_id,
                "beneficiary_name": contato.strip() or None,
                "assignee": "me" if main == me else main,
                "co_assignee_ids": [a for a in form.assignees if a != main],
                "watcher_ids": form.watchers,
                "mention_ids": mention_ids or [],
                "attachment_ids": list(
                    dict.fromkeys([*form.attachments, *await _uploads_in_text(page, db, descricao)])
                ),
            }
        )
        ticket = await tickets_api.create_ticket(data, page.auth, db, Response())
    except ValidationError:
        error = page.t("comum.erroInesperado")
    except HTTPException as exc:
        error = page.api_message(exc)
    else:
        response = RedirectResponse(f"/chamados/{ticket.number}", status_code=303)
        page.flash(response, ("success", page.t("novoChamado.registrado", numero=ticket.number)))
        return response
    return await _new_ticket_page(page, db, form, error=error, status_code=422)


@router.get("/clientes/opcoes")
async def client_options(page: LoggedPageDep, db: DB, q: str = "") -> HTMLResponse:
    """Opções do campo de cliente (HTMX): busca por nome ou nome fantasia, só os ativos."""
    options = (await clients_api.client_options(page.auth, db, q=q.strip()[:200] or None)).items
    return page.render("tickets/_client_options.html", options=options)


# --- detalhe -------------------------------------------------------------------------------


@dataclass
class CommentForm:
    """A caixa de tarefa nova, ou a edição de uma tarefa (`comment_id`)."""

    body: str = ""
    time: str = ""
    done: DateTimeInput = field(default_factory=DateTimeInput.now)
    attachments: list[str] = field(default_factory=list)
    error: str | None = None
    comment_id: str | None = None


async def _ticket_page(
    page: LoggedPage,
    db: DB,
    request: Request,
    number: int,
    *,
    comment: CommentForm | None = None,
    editing: str | None = None,
    removing: str | None = None,
    destination: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    auth = page.auth
    ref = str(number)
    try:
        # Carregado uma vez (visibilidade) e reaproveitado no detalhe e nas tarefas.
        loaded = await tickets_service.load(db, auth, ref)
    except HTTPException as exc:
        if exc.status_code not in (403, 404):
            raise
        return page.render(
            "tickets/unavailable.html",
            status_code=exc.status_code,
            forbidden=exc.status_code == 403,
        )
    # Os trechos pedidos pelo HTMX (editar, remover, grupo de destino) não contam como nova
    # visita nem vão de novo para a auditoria do confidencial.
    if request.headers.get("HX-Request"):
        ticket = await tickets_api.detail(db, auth, loaded)
    else:
        ticket = await tickets_api.open_ticket(db, auth, request, loaded)
    comments = (await tickets_api.comments(db, loaded)).items
    # A última tarefa que a pessoa vê: o aviso de tarefa nova conta a partir dela.
    seen_until = max((c.created_at for c in comments), default=ticket.created_at).isoformat()
    teams = (await organization_api.list_teams(auth, db)).items
    statuses = await catalog_api.status_options(db)
    actions = set(ticket.allowed_actions)
    me = str(auth.user.public_id)
    people = _people(teams)
    watcher_ids = {str(w.id) for w in ticket.watchers}
    delivered = next((s for s in statuses if s.kind == "delivered" and s.is_default), None)
    assignees = [ticket.assignee, *ticket.co_assignees]
    assigned = {str(u.id) for u in assignees}
    outside = [m for m in _members(teams, str(ticket.team.id)) if m[0] not in assigned]
    me_id = auth.user.public_id
    if comment is None and editing:
        # A tarefa em edição (?editar=): só a da própria pessoa.
        found = next(
            (c for c in comments if str(c.id) == editing and c.author and c.author.id == me_id),
            None,
        )
        if found:
            comment = CommentForm(
                body=found.body,
                time=_hhmm(found.time_spent_minutes),
                done=DateTimeInput.at(found.done_at),
                comment_id=str(found.id),
            )
    comment = comment or CommentForm()
    if comment.comment_id is None:
        new_comment, edit_form = comment, None
    else:
        new_comment, edit_form = CommentForm(), comment
    return page.render(
        "tickets/detail.html",
        status_code=status_code,
        ticket=ticket,
        comments=comments,
        actions=actions,
        me=me,
        attachments=_attachments_by_place(ticket, comments),
        people=[{"id": i, "label": n} for i, n in people],
        # Qualquer status (set_status); os concluídos só com set_status_closed (em revisão, só o
        # supervisor ou o admin).
        status_options=[
            (str(s.id), s.name)
            for s in statuses
            if s.kind != "closed" or s.id == ticket.status.id or "set_status_closed" in actions
        ],
        assignees=assignees,
        # "Atribuir a" acrescenta uma pessoa de fora da lista ou o grupo todo ("*").
        assign_options=[("*", page.t("novoChamado.todosDoGrupo")), *outside] if outside else [],
        transfer_teams=[
            (str(t.id), t.name) for t in teams if t.is_active and t.id != ticket.team.id
        ],
        destination=destination,
        destination_members=_members(teams, destination),
        watching=me in watcher_ids,
        watcher_options=[p for p in people if p[0] not in watcher_ids],
        # Marcar como entregue: já entregue, concluído ou cancelado não tem o botão.
        delivered=delivered
        if "set_status" in actions and ticket.status.kind not in ("delivered", "closed", "canceled")
        else None,
        new_comment=new_comment,
        new_pending=await _pending_attachments(page, db, new_comment.attachments),
        edit_form=edit_form,
        removing=removing,
        suggested_times=SUGGESTED_TIMES,
        visto_ate=seen_until,
        viewers=_viewers(page, request, ticket.id),
        new_comments=0,
    )


def _viewers(page: LoggedPage, request: Request, ticket_id: uuid.UUID) -> list[str]:
    """Registra que a pessoa está com o chamado aberto e devolve quem mais está."""
    user = page.auth.user
    names: list[str] = request.app.state.presence.touch(ticket_id, user.id, user.display_name)
    return names


def _since(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


@router.get("/chamados/{number:int}/presenca")
async def presence(
    number: int, page: LoggedPageDep, db: DB, request: Request, desde: str = ""
) -> HTMLResponse:
    """O trecho que a tela pergunta a cada 20 s: quem mais está vendo e as tarefas novas. Passa
    pela visibilidade, mas não conta como visita (novidades) nem vai para a auditoria."""
    ticket = await tickets_service.load(db, page.auth, str(number))
    since = _since(desde)
    return page.render(
        "tickets/_presence.html",
        base=f"/chamados/{number}",
        visto_ate=desde,
        viewers=_viewers(page, request, ticket.public_id),
        new_comments=await tickets_service.comments_since(db, ticket, since, page.auth.user)
        if since
        else 0,
    )


def _attachments_by_place(ticket: TicketOut, comments: list[Any]) -> dict[str | None, list[Any]]:
    """Anexos do registro (chave None) e de cada tarefa, menos as imagens que já estão no texto."""

    def of(comment_id: str | None, text: str) -> list[Any]:
        in_text = set(attachments_in_text(text))
        return [
            a
            for a in ticket.attachments
            if (str(a.comment_id) if a.comment_id else None) == comment_id
            and str(a.id) not in in_text
        ]

    places: dict[str | None, list[Any]] = {None: of(None, ticket.description)}
    for c in comments:
        places[str(c.id)] = of(str(c.id), c.body)
    return places


@router.get("/chamados/{number:int}")
async def ticket_page(
    number: int,
    page: LoggedPageDep,
    db: DB,
    request: Request,
    editar: str | None = None,
    remover: str | None = None,
    team_id: str = "",
) -> HTMLResponse:
    # editar/remover/team_id: o HTMX pede a página com a tarefa em edição, a confirmação da
    # remoção ou os membros do grupo de destino da transferência e troca só esse trecho
    # (hx-select).
    return await _ticket_page(
        page, db, request, number, editing=editar, removing=remover, destination=team_id
    )


def _hhmm(minutes: int | None) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}" if minutes else ""


async def _act(
    page: LoggedPage,
    number: int,
    csrf_token: str,
    action: Callable[[], Awaitable[object]],
    done: str | None,
) -> RedirectResponse:
    """Ação da lateral: executa, volta ao chamado e mostra o resultado no canto."""
    check_csrf(page, csrf_token)
    response = RedirectResponse(f"/chamados/{number}", status_code=303)
    try:
        await action()
    except ValidationError:
        page.flash(response, ("error", page.t("comum.erroInesperado")))
    except HTTPException as exc:
        # 412: outra pessoa mudou os campos depois que a tela abriu (o ETag em `versao`).
        message = page.t("chamado.mudou") if exc.status_code == 412 else page.api_message(exc)
        page.flash(response, ("error", message))
    else:
        if done:
            page.flash(response, ("success", page.t(done)))
    return response


@router.post("/chamados/{number:int}/assumir")
async def take(number: int, page: LoggedPageDep, db: DB, csrf_token: Field = "") -> Response:
    return await _act(
        page,
        number,
        csrf_token,
        lambda: tickets_api.assign_ticket(str(number), AssignIn(assignee="me"), page.auth, db),
        "chamado.feito.assumido",
    )


@router.post("/chamados/{number:int}/responsaveis")
async def set_assignees(
    number: int, page: LoggedPageDep, db: DB, csrf_token: Field = "", responsaveis: Ids = None
) -> Response:
    """A lista inteira de responsáveis (`PUT /assignees`): acrescentar uma pessoa, o grupo todo
    ("*") ou tirar alguém. O principal continua se estiver na lista."""

    async def action() -> None:
        ids = responsaveis or []
        if "*" in ids:
            ticket = await tickets_api.load_detail(db, page.auth, str(number))
            teams = (await organization_api.list_teams(page.auth, db)).items
            ids = [*ids, *(m[0] for m in _members(teams, str(ticket.team.id)))]
        data = AssigneesIn.model_validate(
            {"assignee_ids": list(dict.fromkeys(i for i in ids if i != "*"))}
        )
        await tickets_api.set_ticket_assignees(str(number), data, page.auth, db)

    return await _act(page, number, csrf_token, action, "chamado.feito.atribuido")


def _update(page: LoggedPage, db: DB, number: int, data: TicketUpdate, versao: str) -> Any:
    """PATCH com o ETag que a tela mostrou (`versao`): 412 se outra pessoa mudou os campos."""
    return tickets_api.update_ticket(str(number), data, page.auth, db, Response(), versao or None)


@router.post("/chamados/{number:int}/status")
async def change_status(
    number: int,
    page: LoggedPageDep,
    db: DB,
    csrf_token: Field = "",
    status_id: Field = "",
    versao: Field = "",
) -> Response:
    return await _act(
        page,
        number,
        csrf_token,
        lambda: _update(
            page, db, number, TicketUpdate.model_validate({"status_id": status_id}), versao
        ),
        "chamado.feito.status",
    )


@router.post("/chamados/{number:int}/entregar")
async def deliver(
    number: int, page: LoggedPageDep, db: DB, csrf_token: Field = "", versao: Field = ""
) -> Response:
    """Um clique leva ao status padrão do comportamento Entregue (a revisão do supervisor)."""

    async def action() -> None:
        statuses = await catalog_api.status_options(db)
        delivered = next((s for s in statuses if s.kind == "delivered" and s.is_default), None)
        if delivered is None:  # o admin mudou os status com a página aberta
            raise HTTPException(404, "Status não encontrado.")
        await _update(page, db, number, TicketUpdate(status_id=delivered.id), versao)

    return await _act(page, number, csrf_token, action, "chamado.entregue.feito")


@router.post("/chamados/{number:int}/cliente")
async def change_client(
    number: int,
    page: LoggedPageDep,
    db: DB,
    csrf_token: Field = "",
    client_id: Field = "",
    versao: Field = "",
) -> Response:
    return await _act(
        page,
        number,
        csrf_token,
        lambda: _update(
            page, db, number, TicketUpdate.model_validate({"client_id": client_id}), versao
        ),
        "chamado.feito.cliente",
    )


@router.post("/chamados/{number:int}/transferir")
async def transfer(
    number: int,
    page: LoggedPageDep,
    db: DB,
    csrf_token: Field = "",
    team_id: Field = "",
    assignee_id: Field = "",
    motivo: Field = "",
) -> Response:
    if not motivo.strip():
        check_csrf(page, csrf_token)
        response = RedirectResponse(f"/chamados/{number}", status_code=303)
        page.flash(response, ("error", page.t("chamado.informeMotivo")))
        return response
    return await _act(
        page,
        number,
        csrf_token,
        lambda: tickets_api.transfer_ticket(
            str(number),
            TransferIn.model_validate(
                {"team_id": team_id, "assignee_id": assignee_id, "reason": motivo}
            ),
            page.auth,
            db,
        ),
        "chamado.feito.transferido",
    )


@router.post("/chamados/{number:int}/cancelar")
async def cancel(number: int, page: LoggedPageDep, db: DB, csrf_token: Field = "") -> Response:
    """Só a confirmação, sem motivo."""
    return await _act(
        page,
        number,
        csrf_token,
        lambda: tickets_api.transition_ticket(
            str(number), TransitionIn(action="cancel"), page.auth, db
        ),
        "chamado.feito.cancel",
    )


@router.post("/chamados/{number:int}/observadores")
async def watchers(
    number: int,
    page: LoggedPageDep,
    db: DB,
    csrf_token: Field = "",
    user_id: Field = "",
    observar: Field = "1",
) -> Response:
    watching = observar == "1"
    me = user_id == str(page.auth.user.public_id)
    done = {
        (True, True): "chamado.feito.acompanhando",
        (True, False): "chamado.feito.deixouDeAcompanhar",
        (False, True): "chamado.feito.observador",
        (False, False): "chamado.feito.observadorRemovido",
    }[(me, watching)]
    api_call = tickets_api.add_watcher if watching else tickets_api.remove_watcher

    return await _act(
        page,
        number,
        csrf_token,
        lambda: api_call(str(number), UUID.validate_python(user_id), page.auth, db),
        done,
    )


@router.post("/chamados/{number:int}/tarefas")
async def add_comment(
    number: int,
    page: LoggedPageDep,
    db: DB,
    request: Request,
    csrf_token: Field = "",
    texto: Field = "",
    tempo: Field = "",
    acao: Field = "",
    visto_ate: Field = "",
    attachment_ids: Ids = None,
    mention_ids: Ids = None,
) -> Response:
    """Tarefa nova (comentário na API) e, na mesma ação, retomar ou reabrir (docs/10 §10.6).

    Se chegou tarefa de outra pessoa depois da última que a tela mostrava (`visto_ate`), não
    grava: a página volta com ela à vista e o texto preservado, e o próximo envio passa."""
    check_csrf(page, csrf_token)
    form = CommentForm(body=texto, time=tempo, attachments=attachment_ids or [])

    async def fail(message: str) -> HTMLResponse:
        form.error = message
        return await _ticket_page(page, db, request, number, comment=form, status_code=422)

    try:
        minutes = parse_duration(tempo)
    except ValueError:
        return await fail(page.t("chamado.tempoInvalido"))
    has_text = bool(texto.strip())
    if acao not in ("", "resume", "reopen"):
        return await fail(page.t("comum.erroInesperado"))
    if acao == "reopen" and not has_text:
        return await fail(page.t("chamado.textoObrigatorio.reopen"))
    if minutes and not has_text:
        return await fail(page.t("chamado.tempoSemTexto"))
    if not acao and not has_text:  # nada a enviar
        return RedirectResponse(f"/chamados/{number}", status_code=303)

    attachments = list(dict.fromkeys([*form.attachments, *await _uploads_in_text(page, db, texto)]))
    ref = str(number)
    if since := _since(visto_ate):
        ticket = await tickets_service.load(db, page.auth, ref)
        if await tickets_service.comments_since(db, ticket, since, page.auth.user):
            return await fail(page.t("chamado.tarefaNova"))
    try:
        if acao:
            transition = TransitionIn.model_validate(
                {
                    "action": acao,
                    "comment": texto,
                    "time_spent_minutes": minutes,
                    "mention_ids": mention_ids or [],
                    "attachment_ids": attachments,
                }
            )
            await tickets_api.transition_ticket(ref, transition, page.auth, db)
        else:
            comment = CommentIn.model_validate(
                {
                    "body": texto,
                    "time_spent_minutes": minutes,
                    "mention_ids": mention_ids or [],
                    "attachment_ids": attachments,
                }
            )
            await tickets_api.add_comment(ref, comment, page.auth, db)
    except ValidationError:
        return await fail(page.t("comum.erroInesperado"))
    except HTTPException as exc:
        return await fail(page.api_message(exc))
    response = RedirectResponse(f"/chamados/{number}", status_code=303)
    page.flash(
        response, ("success", page.t(f"chamado.feito.{acao}" if acao else "chamado.comentado"))
    )
    return response


@router.post("/chamados/{number:int}/tarefas/{comment_id}")
async def edit_comment(
    number: int,
    comment_id: str,
    page: LoggedPageDep,
    db: DB,
    request: Request,
    csrf_token: Field = "",
    texto: Field = "",
    tempo: Field = "",
    feita_data: Field = "",
    feita_hora: Field = "",
    feita_ajustado: Field = "",
    mention_ids: Ids = None,
) -> Response:
    """O autor edita o texto, o tempo gasto e a data e hora da tarefa a qualquer momento."""
    check_csrf(page, csrf_token)
    form = CommentForm(
        body=texto,
        time=tempo,
        done=DateTimeInput.from_form(feita_data, feita_hora, feita_ajustado),
        comment_id=comment_id,
    )

    def back(message: str) -> RedirectResponse:
        """Tarefa que não existe ou não é de quem pediu: não há formulário onde mostrar."""
        response = RedirectResponse(f"/chamados/{number}", status_code=303)
        page.flash(response, ("error", message))
        return response

    try:
        comment_uuid = UUID.validate_python(comment_id)
        minutes = parse_duration(tempo)
    except ValidationError:
        return back(page.t("comum.erroInesperado"))
    except ValueError:
        form.error = page.t("chamado.tempoInvalido")
    else:
        if form.done.invalid:
            form.error = page.t("dataHora.invalida")
    if form.error is None:
        try:
            data = CommentIn.model_validate(
                {
                    "body": texto,
                    "time_spent_minutes": minutes,
                    "done_at": form.done.value() or datetime.now(UTC),
                    "mention_ids": mention_ids or [],
                    "attachment_ids": await _uploads_in_text(page, db, texto),
                }
            )
            await tickets_api.edit_comment(str(number), comment_uuid, data, page.auth, db)
        except ValidationError:
            form.error = page.t("comum.erroInesperado")
        except HTTPException as exc:
            if exc.status_code in (403, 404):
                return back(page.api_message(exc))
            form.error = page.api_message(exc)
        else:
            return RedirectResponse(f"/chamados/{number}#tarefa-{comment_id}", status_code=303)
    return await _ticket_page(page, db, request, number, comment=form, status_code=422)


@router.post("/chamados/{number:int}/tarefas/{comment_id}/remover")
async def remove_comment(
    number: int, comment_id: str, page: LoggedPageDep, db: DB, csrf_token: Field = ""
) -> Response:
    return await _act(
        page,
        number,
        csrf_token,
        lambda: tickets_api.delete_comment(
            str(number), UUID.validate_python(comment_id), page.auth, db
        ),
        None,
    )
