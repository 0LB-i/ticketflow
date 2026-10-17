"""Telas de login, senha esquecida, convite, redefinição e troca de senha (docs/09 §9.9).

As regras ficam nas rotas da API (`identity/router.py`): estas só montam a tela e chamam as
mesmas funções.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from chamados.db.session import DB
from chamados.modules.identity import router as api
from chamados.modules.identity.deps import SettingsDep
from chamados.modules.identity.schemas import (
    ChangePasswordIn,
    ForgotIn,
    LoginIn,
    TokenInfo,
    TokenPasswordIn,
)
from chamados.web.page import (
    HOME,
    LoggedPageDep,
    Page,
    PageDep,
    Redirect,
    check_csrf,
    safe_next,
)

router = APIRouter()

Field = Annotated[str, Form()]


@router.get("/login")
async def login_page(
    page: PageDep, volta: str | None = None, expirou: bool = False, aviso: str | None = None
) -> HTMLResponse:
    # Logado não precisa da tela de login.
    if page.auth:
        raise Redirect(safe_next(volta))
    return page.render(
        "auth/login.html", volta=safe_next(volta), expired=expirou, password_created=bool(aviso)
    )


@router.post("/login")
async def login(
    page: PageDep,
    request: Request,
    db: DB,
    settings: SettingsDep,
    login: Field = "",
    senha: Field = "",
    volta: Field = HOME,
) -> Response:
    response = RedirectResponse(safe_next(volta), status_code=303)
    try:
        await api.login(LoginIn(login=login, password=senha), request, response, db, settings)
    except ValidationError:
        error, status = page.t("login.falhou"), 422
    except HTTPException as exc:
        error, status = page.api_message(exc), exc.status_code
    else:
        return response
    return page.render(
        "auth/login.html", status_code=status, volta=safe_next(volta), login=login, error=error
    )


@router.post("/sair")
async def logout(
    page: LoggedPageDep, request: Request, db: DB, settings: SettingsDep, csrf_token: Field = ""
) -> RedirectResponse:
    check_csrf(page, csrf_token)
    response = RedirectResponse("/login", status_code=303)
    await api.logout(page.auth, request, response, db, settings)
    return response


@router.get("/esqueci-senha")
async def forgot_page(page: PageDep) -> HTMLResponse:
    return page.render("auth/forgot.html")


@router.post("/esqueci-senha")
async def forgot(
    page: PageDep,
    request: Request,
    db: DB,
    settings: SettingsDep,
    tasks: BackgroundTasks,
    email: Field = "",
) -> HTMLResponse:
    # A resposta é sempre a mesma, exista o e-mail ou não (docs/09 §9.4); um endereço mal
    # escrito também não muda nada na tela.
    try:
        data = ForgotIn(email=email)
    except ValidationError:
        pass
    else:
        await api.forgot_password(data, request, db, settings, tasks)
    return page.render("auth/forgot.html", sent=True)


# Convite (primeiro acesso) e redefinição de senha: mesma tela, endereços diferentes.
Purpose = Literal["invite", "password_reset"]


async def _token_info(token: str, db: DB) -> TokenInfo | None:
    try:
        return await api.token_info(token, db)
    except HTTPException:
        return None


async def _set_password_page(
    page: Page, purpose: Purpose, token: str, db: DB, error: str | None = None, status: int = 200
) -> HTMLResponse:
    info = await _token_info(token, db)
    if info is not None and info.purpose != purpose:
        info = None
    return page.render(
        "auth/set_password.html",
        status_code=status if info else 404,
        purpose=purpose,
        info=info,
        error=error,
    )


async def _set_password(
    page: Page, purpose: Purpose, token: str, senha: str, confirmar: str, request: Request, db: DB
) -> Response:
    if senha != confirmar:
        return await _set_password_page(
            page, purpose, token, db, page.t("definirSenha.naoConfere"), 422
        )
    accept = api.accept_invite if purpose == "invite" else api.reset_password
    try:
        await accept(TokenPasswordIn(token=token, password=senha), request, db)
    except ValidationError:
        return await _set_password_page(page, purpose, token, db, page.t("comum.erroInesperado"))
    except HTTPException as exc:
        return await _set_password_page(
            page, purpose, token, db, page.api_message(exc), exc.status_code
        )
    return RedirectResponse("/login?aviso=senha-criada", status_code=303)


@router.get("/convite/{token}")
async def invite_page(token: str, page: PageDep, db: DB) -> HTMLResponse:
    return await _set_password_page(page, "invite", token, db)


@router.post("/convite/{token}")
async def accept_invite(
    token: str, page: PageDep, request: Request, db: DB, senha: Field = "", confirmar: Field = ""
) -> Response:
    return await _set_password(page, "invite", token, senha, confirmar, request, db)


@router.get("/redefinir-senha/{token}")
async def reset_page(token: str, page: PageDep, db: DB) -> HTMLResponse:
    return await _set_password_page(page, "password_reset", token, db)


@router.post("/redefinir-senha/{token}")
async def reset_password(
    token: str, page: PageDep, request: Request, db: DB, senha: Field = "", confirmar: Field = ""
) -> Response:
    return await _set_password(page, "password_reset", token, senha, confirmar, request, db)


@router.get("/trocar-senha")
async def change_password_page(page: LoggedPageDep) -> HTMLResponse:
    """Troca obrigatória da senha provisória, logo depois do primeiro acesso (docs/09 §9.2)."""
    if not page.auth.user.must_change_password:
        raise Redirect(HOME)
    return page.render("auth/change_password.html")


@router.post("/trocar-senha")
async def change_password(
    page: LoggedPageDep,
    request: Request,
    db: DB,
    csrf_token: Field = "",
    senha: Field = "",
    confirmar: Field = "",
) -> Response:
    check_csrf(page, csrf_token)
    if not page.auth.user.must_change_password:
        raise Redirect(HOME)
    if senha != confirmar:
        error, status = page.t("definirSenha.naoConfere"), 422
    else:
        try:
            await api.change_password(ChangePasswordIn(new_password=senha), page.auth, request, db)
        except ValidationError:
            error, status = page.t("comum.erroInesperado"), 422
        except HTTPException as exc:
            error, status = page.api_message(exc), exc.status_code
        else:
            return RedirectResponse(HOME, status_code=303)
    return page.render("auth/change_password.html", status_code=status, error=error)
