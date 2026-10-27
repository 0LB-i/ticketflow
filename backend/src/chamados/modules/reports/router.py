"""Relatórios (docs/14 §14.7 e §14.8): números na tela e o mesmo conteúdo em PDF e em CSV."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from chamados.core.i18n import Locale, request_locale
from chamados.db.session import DB
from chamados.modules.audit.service import record
from chamados.modules.identity.deps import CurrentAuth
from chamados.modules.reports import csv_export, model_pdf, service
from chamados.modules.reports.schemas import Report, ReportOptions

router = APIRouter(prefix="/reports", tags=["relatórios"])


async def _filters(
    auth: CurrentAuth,
    db: DB,
    start: Annotated[date, Query(description="primeiro dia do período")],
    end: Annotated[date, Query(description="último dia do período (incluído)")],
    team: Annotated[
        list[uuid.UUID] | None, Query(description="grupo atual do chamado; repita para vários")
    ] = None,
    person: Annotated[
        list[uuid.UUID] | None,
        Query(description="quem fez a tarefa ou é responsável pelo chamado; repita para vários"),
    ] = None,
    client: Annotated[
        list[uuid.UUID] | None, Query(description="cliente do chamado; repita para vários")
    ] = None,
    no_client: Annotated[
        bool, Query(description="inclui os chamados sem cliente (junto com `client`)")
    ] = False,
    status: Annotated[
        list[int] | None, Query(description="status atual do chamado (id); repita para vários")
    ] = None,
) -> service.Filters:
    return await service.resolve(
        db,
        auth,
        start=start,
        end=end,
        teams=team or [],
        people=person or [],
        clients=client or [],
        no_client=no_client,
        statuses=status or [],
    )


Filters = Annotated[service.Filters, Depends(_filters)]
ExportLocale = Annotated[
    Locale | None, Query(description="idioma do arquivo; sem ele, o do Accept-Language")
]


def record_export(
    db: DB, request: Request, auth: CurrentAuth, f: service.Filters, **details: str
) -> None:
    """Cada download vai para a auditoria, com o período e os filtros (também o CSV de um bloco,
    que sai da tela: web/reports.py)."""
    record(
        db,
        "report.exported",
        request=request,
        actor_user_id=auth.user.id,
        target_type="report",
        after={
            **details,
            "start": f.start.isoformat(),
            "end": f.end.isoformat(),
            "teams": [t.name for t in f.teams],
            "people": [p.display_name for p in f.people],
            "clients": [c.label for c in f.clients],
            "no_client": f.no_client,
            "statuses": [s.name for s in f.statuses],
        },
    )


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
    locale: ExportLocale = None,
) -> Response:
    known = await service.lookups(db)
    data = await service.build(db, auth, f, known=known)
    use = await service.schedule_use(db, auth, f, known.calendar)
    content = await run_in_threadpool(
        model_pdf.render_hours,
        data,
        f,
        use,
        auth.user.display_name,
        locale or request_locale(request),
    )
    record_export(db, request, auth, f, format="pdf")
    await db.commit()
    name = f"relatorio-{f.start:%Y-%m-%d}-a-{f.end:%Y-%m-%d}.pdf"
    return Response(
        content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/csv", response_class=Response)
async def report_csv(
    f: Filters,
    auth: CurrentAuth,
    db: DB,
    request: Request,
    table: Annotated[
        csv_export.Table,
        Query(description="people, clients ou overtime: a tabela da tela; tasks: todas as tarefas"),
    ],
    locale: ExportLocale = None,
) -> Response:
    data = await service.build(db, auth, f, all_tasks=table == "tasks")
    content = csv_export.render(data, table, locale or request_locale(request))
    record_export(db, request, auth, f, format="csv", table=table)
    await db.commit()
    name = f"relatorio-{csv_export.FILE_NAMES[table]}-{f.start:%Y-%m-%d}-a-{f.end:%Y-%m-%d}.csv"
    return Response(
        content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
