"""A engine do app (a mesma do worker e do CLI) conecta com os prazos do PostgreSQL."""

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


def test_prazos_da_engine(_no_ar: TestClient) -> None:
    engine: AsyncEngine = _no_ar.app.state.engine  # type: ignore[attr-defined]

    async def ler() -> tuple[str, str]:
        async with engine.connect() as conn:
            stmt = await conn.scalar(text("SHOW statement_timeout"))
            idle = await conn.scalar(text("SHOW idle_in_transaction_session_timeout"))
            return str(stmt), str(idle)

    assert _no_ar.portal is not None
    assert _no_ar.portal.call(ler) == ("1min", "5min")
