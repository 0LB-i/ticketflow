"""Login, sessão, convite, redefinição e troca de senha (docs/09 §9.9); os tokens de API da
pessoa (docs/05)."""

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from chamados.core.permissions import effective_permissions
from chamados.db.session import DB
from chamados.modules.audit.service import client_ip, record
from chamados.modules.identity import ratelimit
from chamados.modules.identity.deps import CurrentAuth, SettingsDep, require_session
from chamados.modules.identity.models import ApiToken, User
from chamados.modules.identity.passwords import hash_password, password_problem, verify_password
from chamados.modules.identity.schemas import (
    ApiTokenCreated,
    ApiTokenIn,
    ApiTokenList,
    ApiTokenOut,
    ChangePasswordIn,
    ForgotIn,
    LoginIn,
    Me,
    MeTeam,
    MeUpdate,
    TokenInfo,
    TokenPasswordIn,
)
from chamados.modules.identity.service import (
    RESET_EVERY,
    find_token,
    issue_token,
    link,
    recently_issued,
    send_link_email,
    send_locked_email,
)
from chamados.modules.identity.sessions import clear_cookies, create_session, now, revoke_sessions
from chamados.modules.identity.tokens import issue_api_token, revoke_api_token
from chamados.modules.organization.models import TeamMember
from chamados.modules.system.service import user_locale

router = APIRouter(tags=["autenticação"])

# O Argon2 gasta ~100 ms de CPU de propósito. Ele roda em run_in_threadpool para não travar as
# outras requisições enquanto isso (a API é um processo só).

INVALID = "E-mail ou senha inválidos."


@router.post("/auth/login", status_code=204)
async def login(
    data: LoginIn, request: Request, response: Response, db: DB, settings: SettingsDep
) -> None:
    ip = client_ip(request) or "desconhecido"
    wait, attempt = await ratelimit.ip_attempt(db, ip)
    if attempt is None:
        raise HTTPException(
            429, "Muitas tentativas. Tente de novo mais tarde.", {"Retry-After": str(wait)}
        )

    login_id = data.login.strip()
    # A linha fica travada até o commit: tentativas simultâneas na mesma conta esperam a anterior
    # e já contam a falha dela (senão todas passariam pela mesma contagem).
    user = await db.scalar(
        select(User)
        .where(or_(User.email == login_id, User.username == login_id))
        .with_for_update(of=User)
    )
    t = now()

    def fail(reason: str) -> HTTPException:
        record(
            db,
            "auth.login_failed",
            request=request,
            actor_user_id=user.id if user else None,
            after={"login": login_id, "motivo": reason},
        )
        return HTTPException(401, INVALID)

    if user is None or not user.is_active or user.password_hash is None:
        await run_in_threadpool(verify_password, None, data.password)  # mesmo tempo de resposta
        exc = fail("conta inexistente ou inativa")
        await db.commit()
        raise exc
    failures, last_failed_at = await ratelimit.account_failures(db, user.id, ip)
    if ratelimit.account_must_wait(failures, last_failed_at, t):
        exc = fail("conta em espera")
        await db.commit()
        raise exc

    ok, rehash = await run_in_threadpool(verify_password, user.password_hash, data.password)
    if not ok:
        await ratelimit.account_failed(db, attempt, user.id)
        exc = fail("senha errada")
        locked = failures + 1 == ratelimit.LOCK_AFTER
        if locked:
            record(
                db,
                "auth.locked",
                request=request,
                actor_user_id=user.id,
                target_type="user",
                target_id=user.public_id,
            )
        await db.commit()
        if locked:
            # Tarefas em segundo plano são descartadas quando a rota levanta exceção.
            locale = await user_locale(db, user)
            await run_in_threadpool(send_locked_email, request.app.state.mailer, user, locale)
        raise exc

    user.last_login_at = t
    if rehash:
        user.password_hash = await run_in_threadpool(hash_password, data.password)
    await create_session(db, user, request, response, settings)
    record(db, "auth.login", request=request, actor_user_id=user.id)
    await ratelimit.ip_succeeded(db, attempt)
    await ratelimit.forget_account(db, user.id, ip)
    await db.commit()


@router.post("/auth/logout", status_code=204)
async def logout(
    auth: CurrentAuth, request: Request, response: Response, db: DB, settings: SettingsDep
) -> None:
    require_session(auth).revoked_at = now()
    record(db, "auth.logout", request=request, actor_user_id=auth.user.id)
    await db.commit()
    clear_cookies(response, settings)


@router.post("/auth/password/forgot", status_code=202)
async def forgot_password(
    data: ForgotIn, request: Request, db: DB, settings: SettingsDep, tasks: BackgroundTasks
) -> None:
    """Sempre responde igual, exista o e-mail ou não, e também quando o pedido repete o de
    menos de 5 minutos, que não manda outro link (docs/09 §9.4)."""
    # A linha travada impede que pedidos simultâneos passem todos pela conferência do intervalo.
    user = await db.scalar(select(User).where(User.email == data.email).with_for_update(of=User))
    if user is None or not user.is_active or user.password_hash is None:
        return
    if await recently_issued(db, user, "password_reset", RESET_EVERY):
        return
    raw = await issue_token(db, user, "password_reset")
    record(db, "auth.password_reset_requested", request=request, actor_user_id=user.id)
    await db.commit()
    url = link(settings, "password_reset", raw)
    locale = await user_locale(db, user)
    tasks.add_task(send_link_email, request.app.state.mailer, user, "password_reset", url, locale)


@router.get("/auth/tokens/{token}", response_model=TokenInfo)
async def token_info(token: str, db: DB) -> TokenInfo:
    """Para a tela de convite/redefinição mostrar de quem é o link antes do formulário."""
    found = await find_token(db, token)
    if found is None:
        raise HTTPException(404, "Link inválido ou expirado.")
    return TokenInfo(
        purpose=found.purpose,
        email=found.user.email,
        display_name=found.user.display_name,
    )


async def _set_password_with_token(
    data: TokenPasswordIn, purpose: str, request: Request, db: DB
) -> None:
    token = await find_token(db, data.token)
    if token is None or token.purpose != purpose:
        raise HTTPException(404, "Link inválido ou expirado.")
    user = token.user
    if problem := password_problem(data.password, user.email, user.username):
        raise HTTPException(422, problem)
    user.password_hash = await run_in_threadpool(hash_password, data.password)
    user.password_changed_at = now()
    await ratelimit.forget_account(db, user.id)
    token.used_at = now()
    await revoke_sessions(db, user.id)
    action = "auth.invite_accepted" if purpose == "invite" else "auth.password_reset"
    record(db, action, request=request, actor_user_id=user.id)
    await db.commit()


@router.post("/auth/invite/accept", status_code=204)
async def accept_invite(data: TokenPasswordIn, request: Request, db: DB) -> None:
    await _set_password_with_token(data, "invite", request, db)


@router.post("/auth/password/reset", status_code=204)
async def reset_password(data: TokenPasswordIn, request: Request, db: DB) -> None:
    await _set_password_with_token(data, "password_reset", request, db)


@router.get("/me", response_model=Me)
async def me(auth: CurrentAuth, db: DB) -> Me:
    memberships = (
        await db.scalars(
            select(TeamMember)
            .where(TeamMember.user_id == auth.user.id)
            .options(selectinload(TeamMember.team))
            .order_by(TeamMember.team_id)
        )
    ).all()
    return Me(
        id=auth.user.public_id,
        email=auth.user.email,
        username=auth.user.username,
        display_name=auth.user.display_name,
        must_change_password=auth.user.must_change_password,
        role=auth.user.role.code,
        teams=[MeTeam(id=m.team.public_id, name=m.team.name, role=m.role) for m in memberships],
        permissions=effective_permissions(auth.actor),
        locale=auth.user.locale,
    )


@router.patch("/me", response_model=Me)
async def update_me(data: MeUpdate, auth: CurrentAuth, db: DB) -> Me:
    """Preferências da própria pessoa: por enquanto, o idioma."""
    auth.user.locale = data.locale
    await db.commit()
    return await me(auth, db)


@router.post("/me/password", status_code=204)
async def change_password(
    data: ChangePasswordIn, auth: CurrentAuth, request: Request, db: DB
) -> None:
    session = require_session(auth)
    user = auth.user
    # Na troca obrigatória a pessoa acabou de entrar com a senha provisória: não pede de novo.
    if not user.must_change_password:
        ok, _ = await run_in_threadpool(
            verify_password, user.password_hash, data.current_password or ""
        )
        if not ok:
            raise HTTPException(422, "A senha atual não confere.")
    if problem := password_problem(data.new_password, user.email, user.username):
        raise HTTPException(422, problem)
    if (await run_in_threadpool(verify_password, user.password_hash, data.new_password))[0]:
        raise HTTPException(422, "A senha nova precisa ser diferente da atual.")
    user.password_hash = await run_in_threadpool(hash_password, data.new_password)
    user.password_changed_at = now()
    user.must_change_password = False
    await revoke_sessions(db, auth.user.id, keep_id=session.id)
    record(db, "auth.password_changed", request=request, actor_user_id=auth.user.id)
    await db.commit()


# --- tokens de API da própria pessoa (docs/05): só pela sessão, um token não cria outro --------


def _token_out(t: ApiToken) -> ApiTokenOut:
    return ApiTokenOut(
        id=t.public_id,
        name=t.name,
        scope=t.scope,
        created_at=t.created_at,
        expires_at=t.expires_at,
        last_used_at=t.last_used_at,
    )


@router.get("/me/tokens", response_model=ApiTokenList)
async def list_my_tokens(auth: CurrentAuth, db: DB) -> ApiTokenList:
    """Os tokens não revogados da pessoa (os vencidos também, até serem revogados)."""
    require_session(auth)
    rows = await db.scalars(
        select(ApiToken)
        .where(ApiToken.user_id == auth.user.id, ApiToken.revoked_at.is_(None))
        .order_by(ApiToken.created_at.desc(), ApiToken.id.desc())
    )
    return ApiTokenList(items=[_token_out(t) for t in rows])


@router.post("/me/tokens", response_model=ApiTokenCreated, status_code=201)
async def create_my_token(
    data: ApiTokenIn, auth: CurrentAuth, db: DB, request: Request
) -> ApiTokenCreated:
    require_session(auth)
    name = data.name.strip()
    if not name:
        raise HTTPException(422, "Dê um nome ao token.")
    raw, token = issue_api_token(
        db, auth.user, name, data.scope, data.days, actor_user_id=auth.user.id, request=request
    )
    await db.commit()
    await db.refresh(token)
    return ApiTokenCreated(**dict(_token_out(token)), token=raw)


@router.delete("/me/tokens/{token_id}", status_code=204)
async def revoke_my_token(token_id: uuid.UUID, auth: CurrentAuth, db: DB, request: Request) -> None:
    require_session(auth)
    token = await db.scalar(
        select(ApiToken).where(
            ApiToken.public_id == token_id,
            ApiToken.user_id == auth.user.id,
            ApiToken.revoked_at.is_(None),
        )
    )
    if token is None:
        raise HTTPException(404, "Token não encontrado.")
    revoke_api_token(db, token, actor_user_id=auth.user.id, request=request)
    await db.commit()
