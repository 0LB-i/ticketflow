"""Cria a aplicação FastAPI: a API em /api e as telas do servidor (ADR 0011), na mesma origem
(ADR 0010)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from starlette.exceptions import HTTPException

from chamados import __version__, web
from chamados.config import Settings, get_settings
from chamados.core import health
from chamados.core.errors import register_error_handlers
from chamados.core.logging import configure_logging
from chamados.db.engine import create_engine
from chamados.db.session import make_sessionmaker
from chamados.modules.attachments.router import router as attachments_router
from chamados.modules.audit.router import router as audit_router
from chamados.modules.catalog.router import router as catalog_router
from chamados.modules.clients.router import router as clients_router
from chamados.modules.identity.admin_router import router as users_router
from chamados.modules.identity.idempotency import IdempotencyMiddleware
from chamados.modules.identity.ratelimit import IpLimiter
from chamados.modules.identity.router import router as auth_router
from chamados.modules.notifications.email import make_mailer
from chamados.modules.organization.router import router as organization_router
from chamados.modules.reports.router import router as reports_router
from chamados.modules.system.router import router as system_router
from chamados.modules.tickets.presence import Presence
from chamados.modules.tickets.router import router as tickets_router
from chamados.web.errors import register_web_error_handlers
from chamados.web.page import Redirect, redirect_response
from chamados.web.templating import STATIC_DIR, CachedStaticFiles


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = create_engine(settings.database_url)
        app.state.sessionmaker = make_sessionmaker(app.state.engine)
        yield
        await app.state.engine.dispose()

    app = FastAPI(
        title="TicketFlow",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    register_error_handlers(app)
    app.add_middleware(IdempotencyMiddleware)
    app.state.settings = settings
    app.state.mailer = make_mailer(settings)
    app.state.ip_limiter = IpLimiter()
    app.state.presence = Presence()

    api = APIRouter(prefix="/api")
    api.include_router(health.router)
    v1 = APIRouter(prefix="/v1")
    for router in (
        auth_router,
        users_router,
        organization_router,
        catalog_router,
        clients_router,
        tickets_router,
        attachments_router,
        reports_router,
        system_router,
        audit_router,
    ):
        v1.include_router(router)
    api.include_router(v1)
    app.include_router(api)

    # Rotas /api inexistentes respondem 404 em JSON, e não com a página de erro das telas.
    @app.api_route(
        "/api/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    async def api_not_found(path: str) -> None:
        raise HTTPException(404)

    # Telas do servidor (ADR 0011). Endereço desconhecido: a página de erro (web/errors.py).
    app.add_exception_handler(Redirect, redirect_response)
    register_web_error_handlers(app)
    app.mount("/static", CachedStaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(web.router)
    return app
