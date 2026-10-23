"""O que toda tela do servidor precisa: sessão (opcional), idioma, marca e o render."""

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from typing import Annotated, Any, Literal, cast
from urllib.parse import urlencode, urlsplit

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from chamados.core.i18n import LOCALES
from chamados.core.i18n import translate as translate_api
from chamados.core.permissions import P, can, effective_permissions
from chamados.db.session import DB
from chamados.modules.identity.deps import Auth, SettingsDep, session_auth
from chamados.modules.identity.sessions import CSRF_COOKIE, SESSION_COOKIE, csrf_ok, load_session
from chamados.modules.system.router import Branding, load_branding
from chamados.web.formatting import format_ago, format_datetime, format_duration, format_size
from chamados.web.i18n import translate
from chamados.web.palette import stylesheet
from chamados.web.templating import templates

HOME = "/chamados"
# Com a senha provisória, só isto abre até a troca (docs/09 §9.2).
ALLOWED_BEFORE_PASSWORD_CHANGE = {"/trocar-senha", "/sair"}
FLASH_COOKIE = "tf_aviso"
FlashKind = Literal["success", "error"]


class Redirect(Exception):
    """Interrompe a rota e manda o navegador para outro endereço (main.py trata)."""

    def __init__(self, url: str) -> None:
        self.url = url


def redirect_response(request: Request, error: Exception) -> Response:
    url = cast(Redirect, error).url
    # Num pedido do HTMX (ex.: "Carregar mais" com a sessão expirada), o 303 seria seguido por
    # baixo e a página de login não caberia no trecho: o HTMX troca a página inteira.
    if request.headers.get("HX-Request"):
        return Response(headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)


def safe_next(url: str | None) -> str:
    """Só endereços deste site: "//outro.site" e "/\\outro.site" levariam para fora."""
    if url and url.startswith("/") and not url.startswith(("//", "/\\")):
        return url
    return HOME


def _read_flash(request: Request) -> list[tuple[str, str]]:
    raw = request.cookies.get(FLASH_COOKIE)
    if not raw:
        return []
    try:
        messages = json.loads(base64.urlsafe_b64decode(raw))
        return [(str(kind), str(text)) for kind, text in messages]
    except (binascii.Error, ValueError, TypeError):
        return []


@dataclass
class Page:
    request: Request
    auth: Auth | None
    branding: Branding
    locale: str

    def t(self, key: str, **values: object) -> str:
        return translate(self.locale, key, **values)

    def api_message(self, exc: HTTPException) -> str:
        """Mensagem de erro de uma rota da API (em português no código), no idioma da tela."""
        return translate_api(str(exc.detail), self.locale)

    def flash(self, response: Response, *messages: tuple[FlashKind, str]) -> None:
        """Avisos (docs/13 §13.6) que a próxima tela mostra no canto, depois de um
        redirecionamento. Sem escapar os acentos: o cookie tem limite de 4 KB."""
        raw = json.dumps(messages, ensure_ascii=False).encode()
        response.set_cookie(
            FLASH_COOKIE,
            base64.urlsafe_b64encode(raw).decode(),
            httponly=True,
            secure=self.request.app.state.settings.cookie_secure,
            samesite="lax",
        )

    def can(self, permission: str) -> bool:
        """Só para mostrar ou esconder botões: quem decide é a rota (ARCHITECTURE 3.4)."""
        return self.auth is not None and permission in effective_permissions(self.auth.actor)

    def render(self, name: str, status_code: int = 200, **context: Any) -> HTMLResponse:
        colors = self.branding.colors
        flashes = _read_flash(self.request)
        response = templates.TemplateResponse(
            self.request,
            name,
            {
                "page": self,
                "t": partial(translate, self.locale),
                "locale": self.locale,
                "branding": self.branding,
                "colors_css": stylesheet(colors.model_dump() if colors else None),
                "csrf_token": self.request.cookies.get(CSRF_COOKIE, ""),
                "flashes": flashes,
                "datetime": partial(format_datetime, self.locale),
                "ago": partial(format_ago, self.locale, now=datetime.now(UTC)),
                "duration": format_duration,
                "size": partial(format_size, self.locale),
                **context,
            },
            status_code=status_code,
        )
        if flashes:
            response.delete_cookie(FLASH_COOKIE)
        # Com sessão, nada fica guardado no navegador: depois de Sair, o Voltar não mostra os
        # dados (clientes, chamados) a quem usar o computador em seguida.
        if self.auth is not None:
            response.headers["Cache-Control"] = "no-store"
        return response


async def get_page(request: Request, db: DB, settings: SettingsDep) -> Page:
    token = request.cookies.get(SESSION_COOKIE)
    session = await load_session(db, token, settings) if token else None
    auth = session_auth(session) if session else None
    branding = await load_branding(db)
    # O idioma escolhido pela pessoa ou o padrão do sistema (configurações).
    locale = branding.default_locale
    if auth and auth.user.locale in LOCALES:
        locale = auth.user.locale
    return Page(request=request, auth=auth, branding=branding, locale=locale)


PageDep = Annotated[Page, Depends(get_page)]


@dataclass
class LoggedPage(Page):
    auth: Auth


async def get_logged_page(page: PageDep) -> LoggedPage:
    """Tela que exige login: sem sessão, vai para o login e depois volta."""
    request = page.request
    if page.auth is None:
        # Depois do login, o navegador abre a "volta" com GET: num POST (sessão expirada no
        # meio do uso), volta para a tela inicial. Num trecho do HTMX, volta para a página em
        # que a pessoa estava, não para o trecho.
        url = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        if current := request.headers.get("HX-Current-URL"):
            parts = urlsplit(current)
            url = safe_next(parts.path + (f"?{parts.query}" if parts.query else ""))
        elif request.method != "GET":
            url = HOME
        if url == HOME:
            raise Redirect("/login")
        raise Redirect(f"/login?{urlencode({'volta': url})}")
    path = request.url.path
    if page.auth.user.must_change_password and path not in ALLOWED_BEFORE_PASSWORD_CHANGE:
        raise Redirect("/trocar-senha")
    return LoggedPage(request=request, auth=page.auth, branding=page.branding, locale=page.locale)


LoggedPageDep = Annotated[LoggedPage, Depends(get_logged_page)]


def requires(permission: P) -> Any:
    """Tela que exige uma permissão global. As rotas de administração da API a conferem numa
    dependência (`require`), que não roda quando a tela chama a função direto: ela é conferida
    aqui."""

    async def dependency(page: LoggedPageDep) -> LoggedPage:
        if not can(page.auth.actor, permission):
            raise HTTPException(403, "Você não tem permissão para esta ação.")
        return page

    return Depends(dependency)


def reject_cross_site(request: Request) -> None:
    """Formulários sem sessão (login, senhas): um envio vindo de outro site é recusado, para
    ninguém fazer o navegador de outra pessoa entrar numa conta alheia."""
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Você não tem permissão para esta ação.")


def check_csrf(page: LoggedPage, token: str) -> None:
    """Formulários que alteram dados mandam o token CSRF da sessão num campo escondido."""
    session = page.auth.session
    if session is None or not csrf_ok(session, token):
        raise HTTPException(403, "Token CSRF ausente ou inválido.")
