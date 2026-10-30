"""Painel do papel Cliente (docs/14 §14.9): a única tela de quem é de uma empresa atendida. Só
leitura, sem filtros nem downloads: o plano, as horas e os chamados do mês. Os números vêm de
`reports/client_panel.py`; as outras telas mandam essa pessoa para cá (`get_logged_page`)."""

from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from chamados.db.session import DB
from chamados.modules.reports.client_panel import client_panel
from chamados.web.formatting import TIMEZONE, format_month
from chamados.web.page import CLIENT_PANEL, LoggedPageDep

router = APIRouter()


@router.get(CLIENT_PANEL)
async def panel_page(page: LoggedPageDep, db: DB) -> HTMLResponse:
    if not page.is_client:
        raise HTTPException(403, "Você não tem permissão para esta ação.")
    today = datetime.now(TIMEZONE).date()
    panel = await client_panel(db, page.auth, today)
    return page.render(
        "client_panel/index.html",
        panel=panel,
        period=str(today.year) if panel.yearly else format_month(page.locale, today),
        month=format_month(page.locale, today),
    )
