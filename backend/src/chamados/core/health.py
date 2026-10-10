"""GET /api/health: confere a aplicação e o banco (docs/18 §18.6)."""

from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from chamados import __version__
from chamados.core.errors import problem

router = APIRouter(tags=["sistema"])


class Health(BaseModel):
    status: Literal["ok"]
    version: str
    database: str


@router.get(
    "/health", response_model=Health, responses={503: {"description": "Banco indisponível"}}
)
async def health(request: Request) -> Health | JSONResponse:
    try:
        async with request.app.state.engine.connect() as conn:
            server_version = (await conn.execute(text("SHOW server_version"))).scalar_one()
    except (SQLAlchemyError, OSError):
        return problem(503, "Banco de dados indisponível")
    return Health(status="ok", version=__version__, database=f"PostgreSQL {server_version}")
