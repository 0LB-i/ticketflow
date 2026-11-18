"""Meu perfil (menu do usuário, no canto de cima): nome de exibição, telefone, cargo, a foto e a
troca da senha. Os dados e a senha passam pelas rotas da API (`PATCH /me`, `POST /me/password`);
a foto, por `identity/profile.py`.
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from chamados.db.session import DB
from chamados.modules.clients import documents as doc
from chamados.modules.identity import profile
from chamados.modules.identity import router as api
from chamados.modules.identity.models import User
from chamados.modules.identity.schemas import ChangePasswordIn, MeUpdate
from chamados.web.page import LoggedPage, LoggedPageDep, check_csrf

router = APIRouter()

Field = Annotated[str, Form()]
HOME = "/perfil"
AVATAR_TYPES = ("image/png", "image/jpeg", "image/webp")


@dataclass
class ProfileForm:
    """O formulário como foi digitado (telefone com máscara)."""

    display_name: str = ""
    job_title: str = ""
    phone: str = ""

    @classmethod
    def of(cls, user: User) -> "ProfileForm":
        return cls(
            user.display_name,
            user.job_title or "",
            doc.format_phone(user.phone) if user.phone else "",
        )

    def errors(self) -> dict[str, str]:
        """Campo → chave do texto do erro, todos de uma vez."""
        found: dict[str, str] = {}
        name = self.display_name.strip()
        if len(name) < 2:
            found["display_name"] = "perfil.nomeCurto" if name else "clientes.erros.obrigatorio"
        elif len(name) > 100:
            found["display_name"] = "clientes.erros.longo"
        if len(self.job_title.strip()) > 100:
            found["job_title"] = "clientes.erros.longo"
        if self.phone.strip() and not doc.valid_phone(doc.normalize_phone(self.phone)):
            found["phone"] = "clientes.erros.telefone"
        return found


async def _render(
    page: LoggedPage,
    db: DB,
    form: ProfileForm,
    errors: dict[str, str] | None = None,
    password_error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    return page.render(
        "profile.html",
        status_code=status_code,
        me=await api.me(page.auth, db),
        form=form,
        errors=errors or {},
        password_error=password_error,
    )


@router.get("/perfil")
async def profile_page(page: LoggedPageDep, db: DB) -> HTMLResponse:
    return await _render(page, db, ProfileForm.of(page.auth.user))


@router.post("/perfil")
async def save_profile(
    page: LoggedPageDep,
    db: DB,
    csrf_token: Field = "",
    display_name: Field = "",
    job_title: Field = "",
    phone: Field = "",
) -> Response:
    """Erro devolve a página com o que foi digitado (422)."""
    check_csrf(page, csrf_token)
    form = ProfileForm(display_name, job_title, phone)
    if errors := form.errors():
        return await _render(page, db, form, errors, status_code=422)
    data = MeUpdate(display_name=display_name, job_title=job_title, phone=phone)
    await api.update_me(data, page.auth, db)
    response = RedirectResponse(HOME, status_code=303)
    page.flash(response, ("success", page.t("comum.salvo")))
    return response


@router.get("/perfil/foto")
async def avatar(page: LoggedPageDep, db: DB) -> Response:
    """A foto da própria pessoa. O endereço leva o hash (`?v=`), então fica no cache."""
    data = await profile.avatar(db, page.auth.user)
    if data is None:
        raise HTTPException(404, "Nenhuma foto cadastrada.")
    return Response(
        data,
        media_type="image/webp",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@router.post("/perfil/foto")
async def save_avatar(
    page: LoggedPageDep,
    db: DB,
    csrf_token: Field = "",
    foto: Annotated[UploadFile | None, File()] = None,
) -> Response:
    """PNG, JPEG ou WebP até 5 MB; escolher a imagem já envia."""
    check_csrf(page, csrf_token)
    response = RedirectResponse(HOME, status_code=303)
    if foto is None or not foto.filename:
        return response
    if foto.content_type not in AVATAR_TYPES:
        page.flash(response, ("error", page.t("perfil.fotoTipo")))
        return response
    raw = await foto.read(profile.AVATAR_MAX_BYTES + 1)
    try:
        await profile.set_avatar(db, page.auth.user, raw)
    except HTTPException as exc:
        page.flash(response, ("error", page.api_message(exc)))
    else:
        page.flash(response, ("success", page.t("perfil.fotoSalva")))
    return response


@router.post("/perfil/foto/remover")
async def remove_avatar(page: LoggedPageDep, db: DB, csrf_token: Field = "") -> Response:
    check_csrf(page, csrf_token)
    await profile.remove_avatar(db, page.auth.user)
    response = RedirectResponse(HOME, status_code=303)
    page.flash(response, ("success", page.t("perfil.fotoRemovida")))
    return response


@router.post("/perfil/senha")
async def change_password(
    page: LoggedPageDep,
    request: Request,
    db: DB,
    csrf_token: Field = "",
    atual: Field = "",
    senha: Field = "",
    confirmar: Field = "",
) -> Response:
    """Troca voluntária: pede a senha atual; as outras sessões da pessoa são encerradas."""
    check_csrf(page, csrf_token)
    form = ProfileForm.of(page.auth.user)
    if senha != confirmar:
        error = page.t("definirSenha.naoConfere")
        return await _render(page, db, form, password_error=error, status_code=422)
    try:
        data = ChangePasswordIn(current_password=atual, new_password=senha)
        await api.change_password(data, page.auth, request, db)
    except ValidationError:
        error, status = page.t("comum.erroInesperado"), 422
    except HTTPException as exc:
        error, status = page.api_message(exc), exc.status_code
    else:
        response = RedirectResponse(HOME, status_code=303)
        page.flash(response, ("success", page.t("trocarSenha.pronto")))
        return response
    return await _render(page, db, form, password_error=error, status_code=status)
