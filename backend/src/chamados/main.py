"""Cria a aplicação FastAPI: API em /api e a SPA compilada na mesma origem (ADR 0010)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from chamados import __version__
from chamados.config import Settings, get_settings
from chamados.core import health
from chamados.core.errors import register_error_handlers
from chamados.core.logging import configure_logging
from chamados.db.engine import create_engine
from chamados.db.session import make_sessionmaker
from chamados.modules.audit.router import router as audit_router
from chamados.modules.catalog.router import router as catalog_router
from chamados.modules.identity.admin_router import router as users_router
from chamados.modules.identity.ratelimit import IpLimiter
from chamados.modules.identity.router import router as auth_router
from chamados.modules.notifications.email import make_mailer
from chamados.modules.organization.router import router as organization_router
from chamados.modules.system.router import router as system_router
from chamados.modules.tickets.router import router as tickets_router


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
    app.state.settings = settings
    app.state.mailer = make_mailer(settings)
    app.state.ip_limiter = IpLimiter()

    api = APIRouter(prefix="/api")
    api.include_router(health.router)
    v1 = APIRouter(prefix="/v1")
    for router in (
        auth_router,
        users_router,
        organization_router,
        catalog_router,
        tickets_router,
        system_router,
        audit_router,
    ):
        v1.include_router(router)
    api.include_router(v1)
    app.include_router(api)

    # Rotas /api inexistentes respondem 404 em JSON, em vez de cair no index.html da SPA.
    @app.api_route(
        "/api/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    async def api_not_found(path: str) -> None:
        raise HTTPException(404)

    _mount_spa(app, settings)
    return app


def _mount_spa(app: FastAPI, settings: Settings) -> None:
    """Serve frontend/dist. Rotas desconhecidas devolvem o index.html (roteamento da SPA)."""
    dist = settings.frontend_dist.resolve()
    index = dist / "index.html"
    if not index.is_file():
        return
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        file = (dist / path).resolve()
        if path and file.is_file() and file.is_relative_to(dist):
            return FileResponse(file)
        return FileResponse(index)
