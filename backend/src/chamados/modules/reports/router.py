"""Relatórios (docs/14 §14.7): números na tela e o mesmo conteúdo em PDF."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from chamados.core.i18n import Locale, request_locale
from chamados.db.session import DB
from chamados.modules.audit.service import record
from chamados.modules.identity.deps import CurrentAuth
from chamados.modules.reports import pdf, service
from chamados.modules.reports.schemas import Report, ReportOptions

router = APIRouter(prefix="/reports", tags=["relatórios"])


async def _filters(
    auth: CurrentAuth,
    db: DB,
    start: Annotated[date, Query(description="primeiro dia do período")],
    end: Annotated[date, Query(description="último dia do período (incluído)")],
    team: Annotated[uuid.UUID | None, Query(description="grupo atual do chamado")] = None,
    person: Annotated[uuid.UUID | None, Query(description="quem fez a tarefa")] = None,
    client: Annotated[uuid.UUID | None, Query(description="cliente do chamado")] = None,
) -> service.Filters:
    return await service.resolve(
        db, auth, start=start, end=end, team=team, person=person, client=client
    )


Filters = Annotated[service.Filters, Depends(_filters)]


@router.get("/options", response_model=ReportOptions)
async def report_options(auth: CurrentAuth, db: DB) -> ReportOptions:
    return await service.options(db, auth)


@router.get("", response_model=Report)
async def report(f: Filters, auth: CurrentAuth, db: DB) -> Report:
    return await service.build(db, auth, f)


@router.get("/pdf", response_class=Response)
async def report_pdf(
    f: Filters,
    auth: CurrentAuth,
    db: DB,
    request: Request,
    locale: Annotated[
        Locale | None, Query(description="idioma do PDF; sem ele, o do Accept-Language")
    ] = None,
) -> Response:
    data = await service.build(db, auth, f)
    content = await run_in_threadpool(
        pdf.render, data, f, auth.user.display_name, locale or request_locale(request)
    )
    record(
        db,
        "report.exported",
        request=request,
        actor_user_id=auth.user.id,
        target_type="report",
        after={
            "start": f.start.isoformat(),
            "end": f.end.isoformat(),
            "team": f.team.name if f.team else None,
            "person": f.person.display_name if f.person else None,
            "client": f.client.label if f.client else None,
        },
    )
    await db.commit()
    name = f"relatorio-{f.start:%Y-%m-%d}-a-{f.end:%Y-%m-%d}.pdf"
    return Response(
        content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
