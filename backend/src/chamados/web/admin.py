"""Administração: usuários e grupos (docs/13 §13.5).

Padrão das telas: lista, botão Novo e edição num painel lateral, aberto pelo endereço
(`?novo=1` ou `?editar=<id>`). As regras e a gravação são as rotas da API
(`identity/admin_router.py`, `organization/router.py`); a permissão de cada tela é conferida aqui
por `requires`, porque a da API fica numa dependência que não roda nesta chamada direta.
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, Any
from urllib.parse import parse_qs, urlencode, urlsplit

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select

from chamados.core.permissions import P
from chamados.db.session import DB
from chamados.modules.identity import admin_router as users_api
from chamados.modules.identity.admin_router import LinkOut, UserCreate, UserOut, UserUpdate
from chamados.modules.identity.deps import SettingsDep
from chamados.modules.identity.models import User
from chamados.modules.organization import router as organization_api
from chamados.modules.organization.router import (
    MemberIn,
    TeamCreate,
    TeamOut,
    TeamUpdate,
)
from chamados.modules.tickets import service as tickets_service
from chamados.web.formatting import format_datetime
from chamados.web.page import FlashKind, LoggedPage, check_csrf, requires, safe_next

router = APIRouter()

UsersAdmin = Annotated[LoggedPage, requires(P.ADMIN_USERS)]
OrganizationAdmin = Annotated[LoggedPage, requires(P.ADMIN_ORGANIZATION)]
Field = Annotated[str, Form()]
Ids = Annotated[list[str] | None, Form()]
UUID = TypeAdapter(uuid.UUID)

ROLES = ("agent", "admin", "auditor")
STATUSES = ("ativo", "convite_pendente", "inativo")


def _list_url(base: str, params: dict[str, Any]) -> str:
    """A lista com os filtros em uso: abrir, fechar e salvar no painel não os perde."""
    query = urlencode({k: v for k, v in params.items() if v})
    return f"{base}?{query}" if query else base


def _back(volta: str, base: str) -> str:
    """O endereço da lista que o formulário trouxe (campo volta), só se for da mesma tela."""
    url = safe_next(volta)
    return url if url.split("?")[0] == base else base


def _filters(volta: str, base: str) -> dict[str, str]:
    """Os filtros da lista que o formulário trouxe (volta): a tela que volta com erro, ou a do
    link de acesso, continua filtrada."""
    query = parse_qs(urlsplit(_back(volta, base)).query)
    return {k: v[0] for k, v in query.items() if k not in ("editar", "novo")}


def _inactive(volta: str, base: str) -> bool:
    return _filters(volta, base).get("inativos") == "true"


USER_FILTERS = ("q", "papel", "grupo", "situacao")


def _user_filters(volta: str) -> dict[str, str]:
    found = _filters(volta, "/admin/usuarios")
    return {k: found.get(k, "") for k in USER_FILTERS}


def _with(url: str, **params: object) -> str:
    return f"{url}{'&' if '?' in url else '?'}{urlencode(params)}"


def _list_context(base: str, filters: dict[str, Any]) -> dict[str, Any]:
    back = _list_url(base, filters)
    return {"back": back, "panel_url": lambda **params: _with(back, **params)}


async def _run(
    page: LoggedPage,
    back: str,
    action: Callable[[], Awaitable[object]],
    done: str | None,
    warning: Callable[[], Awaitable[str | None]] | None = None,
) -> RedirectResponse:
    """Ação de um botão: executa e volta com o aviso (o erro da API vira aviso também).
    `warning`: depois do sucesso, um alerta que fica na tela até a pessoa fechar."""
    response = RedirectResponse(back, status_code=303)
    try:
        await action()
    except ValidationError:
        page.flash(response, ("error", page.t("comum.erroInesperado")))
    except HTTPException as exc:
        page.flash(response, ("error", page.api_message(exc)))
    else:
        messages: list[tuple[FlashKind, str]] = [("success", done)] if done else []
        if warning and (text := await warning()):
            messages.append(("error", text))
        if messages:
            page.flash(response, *messages)
    return response


def _left_with(
    page: LoggedPage, db: DB, user_id: uuid.UUID, team_id: uuid.UUID | None = None
) -> Callable[[], Awaitable[str | None]]:
    """O alerta dos chamados abertos que continuam com quem saiu do sistema ou do grupo: sem
    supervisor no grupo, ninguém os recebeu (tickets.service.release)."""

    async def warning() -> str | None:
        numbers = await tickets_service.still_assigned(db, user_id, team_id)
        if not numbers:
            return None
        name = await db.scalar(select(User.display_name).where(User.public_id == user_id))
        lista = ", ".join(f"#{n}" for n in numbers)
        return page.t("usuarios.chamadosSemSupervisor", lista=lista, nome=name or "")

    return warning


# --- usuários --------------------------------------------------------------------------------


def _user_matches(u: UserOut, q: str, role: str, team: str, status: str) -> bool:
    text = f"{u.full_name} {u.display_name} {u.email or ''} {u.username or ''}".lower()
    return (
        q.strip().lower() in text
        and (not role or u.role == role)
        and (not team or any(str(t.id) == team for t in u.teams))
        and (not status or u.status == status)
    )


async def _users_page(
    page: LoggedPage,
    db: DB,
    *,
    filters: dict[str, str] | None = None,
    editing: str | None = None,
    creating: bool = False,
    form: dict[str, Any] | None = None,
    error: str | None = None,
    link: LinkOut | None = None,
    link_name: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    filters = {k: (filters or {}).get(k, "") for k in USER_FILTERS}
    q, papel, grupo, situacao = (filters[k] for k in USER_FILTERS)
    users = (await users_api.list_users(page.auth, db)).items
    teams = [t for t in (await organization_api.list_teams(page.auth, db)).items if t.is_active]
    edited = next((u for u in users if str(u.id) == editing), None)
    if edited and form is None:
        form = {
            "full_name": edited.full_name,
            "display_name": edited.display_name,
            "email": edited.email or "",
            "username": edited.username or "",
            "role": edited.role,
        }
    return page.render(
        "admin/users.html",
        status_code=status_code,
        **_list_context(
            "/admin/usuarios", {"q": q, "papel": papel, "grupo": grupo, "situacao": situacao}
        ),
        users=[u for u in users if _user_matches(u, q, papel, grupo, situacao)],
        filters={"q": q, "papel": papel, "grupo": grupo, "situacao": situacao},
        role_options=[(r, page.t(f"usuarios.papeis.{r}")) for r in ROLES],
        team_options=[(str(t.id), t.name) for t in teams],
        status_options=[(s, page.t(f"usuarios.status.{s}")) for s in STATUSES],
        edited=edited,
        creating=creating and edited is None,
        form=form or {"role": "agent", "team_ids": []},
        error=error,
        link=link,
        link_name=link_name,
        me=str(page.auth.user.public_id),
        last_login=lambda u: (
            format_datetime(page.locale, u.last_login_at)
            if u.last_login_at
            else page.t("comum.nunca")
        ),
    )


@router.get("/admin/usuarios")
async def users_page(
    page: UsersAdmin,
    db: DB,
    q: str = "",
    papel: str = "",
    grupo: str = "",
    situacao: str = "",
    editar: str | None = None,
    novo: bool = False,
) -> HTMLResponse:
    return await _users_page(
        page,
        db,
        filters={"q": q, "papel": papel, "grupo": grupo, "situacao": situacao},
        editing=editar,
        creating=novo,
    )


@router.post("/admin/usuarios/novo")
async def create_user(
    page: UsersAdmin,
    request: Request,
    db: DB,
    csrf_token: Field = "",
    volta: Field = "",
    full_name: Field = "",
    display_name: Field = "",
    email: Field = "",
    username: Field = "",
    password: Field = "",
    role: Field = "agent",
    team_ids: Ids = None,
) -> Response:
    check_csrf(page, csrf_token)
    form = {
        "full_name": full_name,
        "display_name": display_name,
        "email": email,
        "username": username,
        "role": role,
        "team_ids": team_ids or [],
    }
    try:
        data = UserCreate.model_validate({**form, "password": password})
        await users_api.create_user(data, page.auth, request, db)
    except ValidationError:
        error = page.t("comum.erroInesperado")
    except HTTPException as exc:
        error = page.api_message(exc)
    else:
        response = RedirectResponse(_back(volta, "/admin/usuarios"), status_code=303)
        page.flash(response, ("success", page.t("usuarios.criado")))
        return response
    return await _users_page(
        page,
        db,
        filters=_user_filters(volta),
        creating=True,
        form=form,
        error=error,
        status_code=422,
    )


@router.post("/admin/usuarios/{user_id}")
async def update_user(
    user_id: uuid.UUID,
    page: UsersAdmin,
    request: Request,
    db: DB,
    csrf_token: Field = "",
    volta: Field = "",
    full_name: Field = "",
    display_name: Field = "",
    email: Field = "",
    username: Field = "",
    role: Field = "agent",
) -> Response:
    check_csrf(page, csrf_token)
    current = await users_api.get_user(user_id, page.auth, db)
    form = {
        "full_name": full_name,
        "display_name": display_name,
        "email": email,
        "username": username,
        "role": role,
    }
    # E-mail e usuário só vão quando mudam (e nunca vazios: a API não os apaga).
    changes: dict[str, Any] = {"full_name": full_name, "display_name": display_name, "role": role}
    if email.strip() and email.strip() != current.email:
        changes["email"] = email.strip()
    if username.strip() and username.strip() != current.username:
        changes["username"] = username.strip()
    try:
        await users_api.update_user(
            user_id, UserUpdate.model_validate(changes), page.auth, request, db
        )
    except ValidationError:
        error = page.t("comum.erroInesperado")
    except HTTPException as exc:
        error = page.api_message(exc)
    else:
        response = RedirectResponse(_back(volta, "/admin/usuarios"), status_code=303)
        page.flash(response, ("success", page.t("comum.salvo")))
        return response
    return await _users_page(
        page,
        db,
        filters=_user_filters(volta),
        editing=str(user_id),
        form=form,
        error=error,
        status_code=422,
    )


@router.post("/admin/usuarios/{user_id}/reativar")
async def reactivate_user(
    user_id: uuid.UUID,
    page: UsersAdmin,
    request: Request,
    db: DB,
    csrf_token: Field = "",
    volta: Field = "",
) -> Response:
    """Quem foi desativado antes de existir a exclusão ainda pode ser reativado."""
    check_csrf(page, csrf_token)
    return await _run(
        page,
        _with(_back(volta, "/admin/usuarios"), editar=user_id),
        lambda: users_api.update_user(user_id, UserUpdate(is_active=True), page.auth, request, db),
        None,
    )


@router.post("/admin/usuarios/{user_id}/excluir")
async def delete_user(
    user_id: uuid.UUID,
    page: UsersAdmin,
    request: Request,
    db: DB,
    csrf_token: Field = "",
    volta: Field = "",
) -> Response:
    check_csrf(page, csrf_token)
    return await _run(
        page,
        _back(volta, "/admin/usuarios"),
        lambda: users_api.delete_user(user_id, page.auth, request, db),
        page.t("usuarios.excluido"),
        _left_with(page, db, user_id),
    )


@router.post("/admin/usuarios/{user_id}/link")
async def send_link(
    user_id: uuid.UUID,
    page: UsersAdmin,
    request: Request,
    db: DB,
    settings: SettingsDep,
    tasks: BackgroundTasks,
    csrf_token: Field = "",
    volta: Field = "",
) -> Response:
    """Convite ou redefinição. Sem SMTP, a tela mostra o link para o administrador repassar."""
    check_csrf(page, csrf_token)
    back = _with(_back(volta, "/admin/usuarios"), editar=user_id)
    try:
        link = await users_api.send_access_link(user_id, page.auth, request, db, settings, tasks)
    except HTTPException as exc:
        response = RedirectResponse(back, status_code=303)
        page.flash(response, ("error", page.api_message(exc)))
        return response
    if link.url:
        user = await users_api.get_user(user_id, page.auth, db)
        return await _users_page(
            page,
            db,
            filters=_user_filters(volta),
            editing=str(user_id),
            link=link,
            link_name=user.full_name,
        )
    response = RedirectResponse(back, status_code=303)
    page.flash(response, ("success", page.t("usuarios.linkEnviado")))
    return response


# --- grupos ----------------------------------------------------------------------------------


async def _teams_page(
    page: LoggedPage,
    db: DB,
    *,
    inactive: bool = False,
    editing: str | None = None,
    creating: bool = False,
    form: dict[str, Any] | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    teams = (await organization_api.list_teams(page.auth, db)).items
    edited: TeamOut | None = next((t for t in teams if str(t.id) == editing), None)
    if edited and form is None:
        form = {
            "name": edited.name,
            "description": edited.description or "",
            "notify_on_new": edited.notify_on_new,
            "is_active": edited.is_active,
        }
    # Quem pode entrar no grupo vem da lista de usuários (admin.users), como na SPA.
    candidates: list[tuple[str, str]] = []
    if edited and page.can("admin.users"):
        members = {m.user_id for m in edited.members}
        candidates = [
            (str(u.id), f"{u.display_name} ({u.email or u.username})")
            for u in (await users_api.list_users(page.auth, db)).items
            if u.status != "inativo" and u.id not in members
        ]
    return page.render(
        "admin/teams.html",
        status_code=status_code,
        **_list_context("/admin/grupos", {"inativos": "true" if inactive else ""}),
        teams=[t for t in teams if inactive or t.is_active],
        inactive=inactive,
        edited=edited,
        creating=creating and edited is None,
        form=form or {"notify_on_new": "queue_only", "is_active": True},
        error=error,
        notify_options=[
            (n, page.t(f"grupos.avisos.{n}")) for n in ("queue_only", "email_all_members")
        ],
        role_options=[(r, page.t(f"grupos.funcoes.{r}")) for r in ("member", "supervisor")],
        candidates=candidates,
    )


@router.get("/admin/grupos")
async def teams_page(
    page: OrganizationAdmin,
    db: DB,
    inativos: bool = False,
    editar: str | None = None,
    novo: bool = False,
) -> HTMLResponse:
    return await _teams_page(page, db, inactive=inativos, editing=editar, creating=novo)


@router.post("/admin/grupos/novo")
async def create_team(
    page: OrganizationAdmin,
    request: Request,
    db: DB,
    csrf_token: Field = "",
    volta: Field = "",
    name: Field = "",
    description: Field = "",
    notify_on_new: Field = "queue_only",
) -> Response:
    """Criado, o painel continua aberto para incluir os membros."""
    check_csrf(page, csrf_token)
    form = {"name": name, "description": description, "notify_on_new": notify_on_new}
    try:
        data = TeamCreate.model_validate(
            {**form, "name": name.strip(), "description": description.strip() or None}
        )
        team = await organization_api.create_team(data, page.auth, request, db)
    except ValidationError:
        error = page.t("comum.erroInesperado")
    except HTTPException as exc:
        error = page.api_message(exc)
    else:
        response = RedirectResponse(
            _with(_back(volta, "/admin/grupos"), editar=team.id), status_code=303
        )
        page.flash(response, ("success", page.t("grupos.criado")))
        return response
    return await _teams_page(
        page,
        db,
        inactive=_inactive(volta, "/admin/grupos"),
        creating=True,
        form=form,
        error=error,
        status_code=422,
    )


@router.post("/admin/grupos/{team_id}")
async def update_team(
    team_id: uuid.UUID,
    page: OrganizationAdmin,
    request: Request,
    db: DB,
    csrf_token: Field = "",
    volta: Field = "",
    name: Field = "",
    description: Field = "",
    notify_on_new: Field = "queue_only",
    is_active: Field = "",
) -> Response:
    check_csrf(page, csrf_token)
    form = {
        "name": name,
        "description": description,
        "notify_on_new": notify_on_new,
        "is_active": is_active == "1",
    }
    try:
        data = TeamUpdate.model_validate(
            {**form, "name": name.strip(), "description": description.strip() or None}
        )
        await organization_api.update_team(team_id, data, page.auth, request, db)
    except ValidationError:
        error = page.t("comum.erroInesperado")
    except HTTPException as exc:
        error = page.api_message(exc)
    else:
        response = RedirectResponse(_back(volta, "/admin/grupos"), status_code=303)
        page.flash(response, ("success", page.t("comum.salvo")))
        return response
    return await _teams_page(
        page,
        db,
        inactive=_inactive(volta, "/admin/grupos"),
        editing=str(team_id),
        form=form,
        error=error,
        status_code=422,
    )


@router.post("/admin/grupos/{team_id}/membros")
async def put_member(
    team_id: uuid.UUID,
    page: OrganizationAdmin,
    request: Request,
    db: DB,
    csrf_token: Field = "",
    volta: Field = "",
    user_id: Field = "",
    role: Field = "member",
) -> Response:
    """Inclui a pessoa ou muda a função dela no grupo."""
    check_csrf(page, csrf_token)
    return await _run(
        page,
        _with(_back(volta, "/admin/grupos"), editar=team_id),
        lambda: organization_api.put_member(
            team_id,
            UUID.validate_python(user_id),
            MemberIn.model_validate({"role": role}),
            page.auth,
            request,
            db,
        ),
        None,
    )


@router.post("/admin/grupos/{team_id}/membros/{user_id}/remover")
async def remove_member(
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    page: OrganizationAdmin,
    request: Request,
    db: DB,
    csrf_token: Field = "",
    volta: Field = "",
) -> Response:
    check_csrf(page, csrf_token)
    return await _run(
        page,
        _with(_back(volta, "/admin/grupos"), editar=team_id),
        lambda: organization_api.remove_member(team_id, user_id, page.auth, request, db),
        None,
        _left_with(page, db, user_id, team_id),
    )
