"""Relatórios: os downloads da tela (docs/14 §14.8.4 e §14.8.6), com os mesmos filtros e o
idioma da pessoa: o PDF de uma aba, o CSV de um bloco e a lista dos chamados por trás de um
número (detalhar), com o CSV dela. Todo download vai para a
auditoria (`report.exported`).
"""

import re
import unicodedata
from collections.abc import Callable
from datetime import datetime
from typing import Any, cast
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from chamados.core.i18n import Locale
from chamados.db.session import DB
from chamados.modules.reports import builder, csv_export, history, model_pdf, service
from chamados.modules.reports import router as reports_api
from chamados.modules.reports.builder import CHARTS, TICKET_SETS
from chamados.modules.system.company import get_letterhead
from chamados.modules.system.service import get_report_logo
from chamados.web.formatting import TIMEZONE, format_date, format_datetime, format_elapsed
from chamados.web.page import LoggedPage, LoggedPageDep
from chamados.web.palette import palette
from chamados.web.reports_blocks import (
    LISTED,
    Format,
    Point,
    block_view,
    formatter,
    scope,
    uses_overtime,
    work_hours_line,
)
from chamados.web.reports_state import (
    ParamsDep,
    State,
    description_of,
    interval_text,
    load_state,
    with_query,
)

router = APIRouter()


def _ticks(points: list[Point], step: int, fmt: Format) -> list[tuple[int, str]]:
    """As marcas do eixo, como as do _charts.html: o topo, a metade e o zero."""
    highest = max((max(p.value, p.before or 0) for p in points), default=0)
    top = max(step, -(-highest // step) * step)
    return [(top, fmt(top)), (top // 2, fmt(top // 2)), (0, fmt(0))]


def _pdf_blocks(page: LoggedPage, views: list[dict[str, Any]]) -> list[model_pdf.Block]:
    """Os blocos da tela, já formatados, no formato do PDF."""
    blocks: list[model_pdf.Block] = []
    for v in views:
        visual = v["visual"]
        if visual == "cards":
            items = []
            for card in v["cards"]:
                note = ""
                if "before" in card:
                    note = (
                        page.t(
                            "relatorios.comparacao.antes",
                            variacao=card["change"],
                            anterior=card["before"],
                        )
                        if card["change"]
                        else page.t("relatorios.comparacao.soAntes", anterior=card["before"])
                    )
                items.append((card["label"], card["value"], note))
            blocks.append(model_pdf.Cards(v["title"], items))
        elif visual in CHARTS:
            fmt = v["fmt"]
            blocks.append(
                model_pdf.Chart(
                    v["title"],
                    visual,
                    [(p.label, p.value, fmt(p.value)) for p in v["points"]],
                    ticks=_ticks(v["points"], v["step"], fmt),
                    legend=v.get("legend"),
                    empty=v["empty"],
                    before=[p.before for p in v["points"]] if "legend" in v else [],
                )
            )
        elif visual == "table":
            blocks.append(
                model_pdf.Grid(
                    v["title"],
                    v["columns"],
                    [[label, *(text for text, _ in cells)] for label, _, cells in v["rows"]],
                    total=[text for text, _ in v["total"]],
                    total_label=v["total_label"],
                    empty=page.t("relatorios.nada"),
                )
            )
        else:
            # As colunas da tela; o chamado é o número e o título.
            texts: dict[str, Callable[[dict[str, Any]], str]] = {
                "when": lambda t: format_datetime(page.locale, t["done_at"]),
                "ticket": lambda t: f"#{t['number']} {t['title']}",
                "time": lambda t: t["minutes"],
            }
            blocks.append(
                model_pdf.Grid(
                    v["title"],
                    [label for _, label in v["columns"]],
                    [
                        [texts[key](t) if key in texts else t[key] for key, _ in v["columns"]]
                        for t in v["tasks"]
                    ],
                    empty=v["empty"],
                    note=page.t("relatorios.listaCortada", n=len(v["tasks"]), total=v["count"])
                    if v["count"] > len(v["tasks"])
                    else "",
                )
            )
    return blocks


def _filters_line(page: LoggedPage, state: State) -> str:
    """Os filtros usados, para o cabeçalho do PDF (o cliente, não)."""
    o = state.options
    parts = []
    for key, chosen in (
        ("grupo", [t.name for t in o.teams if t.id in state.teams]),
        ("pessoa", [p.name for p in o.people if p.id in state.people]),
    ):
        if chosen:
            parts.append(f"{page.t(f'relatorios.{key}')}: {', '.join(chosen)}")
    return " · ".join(parts)


async def _client_tasks(
    page: LoggedPage, db: DB, state: State, f: service.Filters
) -> list[model_pdf.Block]:
    """O PDF detalhado da aba Clientes: uma tabela por cliente (pelo nome, "Sem cliente" no
    fim) com cada tarefa do período (o dia, o chamado e o tempo; antes dele, com a hora extra
    separada, o tempo no expediente e o extra; sempre, o no plano do cliente e o excedente; com
    horas descontadas, depois do tempo, o desconto e o tempo a cobrar) e o total dele. Da
    tarefa, só o chamado: o texto dela pode ter anotações internas."""
    want = service.Want(rows={"tasks"}, sums={"excess": set(), "discounted": set()})
    data = await service.facts(db, page.auth, f, want, state.lookups)
    hours = formatter(page, "hours")
    by_client: dict[int | None, list[service.TaskFact]] = {}
    for t in data.tasks:
        by_client.setdefault(t.client_id, []).append(t)

    def name(client_id: int | None) -> str:
        found = data.clients.get(client_id) if client_id else None
        return found.label if found else page.t("relatorios.semCliente")

    def times(minutes: int, overtime: int, excess: int, discounted: int) -> list[str]:
        separated = [hours(minutes - overtime), hours(overtime)] if state.separate else []
        discount = [hours(discounted), hours(minutes - discounted)] if f.discount else []
        return [*separated, hours(minutes - excess), hours(excess), hours(minutes), *discount]

    columns = [page.t(f"relatorios.colunas.{c}") for c in ("quando", "chamado")]
    if state.separate:
        columns += [page.t(f"relatorios.medidas.{m}") for m in ("regular", "overtime")]
    columns += [page.t(f"relatorios.medidas.{m}") for m in ("in_plan", "excess")]
    columns.append(page.t("relatorios.colunas.tempo"))
    if f.discount:
        columns += [page.t(f"relatorios.medidas.{m}") for m in ("discounted", "charged")]
    return [
        model_pdf.Grid(
            name(client_id),
            columns,
            [
                [
                    format_date(page.locale, t.done_at),
                    f"#{t.ticket_number} {t.ticket_title}",
                    *times(t.minutes, t.overtime, t.excess, t.discounted),
                ]
                for t in tasks
            ],
            total=[
                "",
                *times(
                    sum(t.minutes for t in tasks),
                    sum(t.overtime for t in tasks),
                    sum(t.excess for t in tasks),
                    sum(t.discounted for t in tasks),
                ),
            ],
            total_label=page.t("relatorios.total"),
        )
        for client_id, tasks in sorted(
            by_client.items(), key=lambda item: (item[0] is None, name(item[0]).casefold())
        )
    ]


def attachment(name: str) -> dict[str, str]:
    """O cabeçalho do download com o nome do arquivo: o nome com acentos (`filename*`) e, para
    quem não o entende, o mesmo sem eles (`filename`)."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return {
        "Content-Disposition": f"attachment; filename=\"{plain}\"; filename*=UTF-8''{quote(name)}"
    }


def file_name(text: str) -> str:
    """Um nome que serve de nome de arquivo: sem / \\ : * ? " < > | e controles."""
    return re.sub(r'[\x00-\x1f/\\:*?"<>|]+', " ", text).strip(" .") or "cliente"


@router.get("/relatorios/pdf")
async def report_pdf(
    page: LoggedPageDep, db: DB, params: ParamsDep, detalhado: bool = False
) -> Response:
    """O PDF da aba aberta (§14.8.6), com os filtros da tela; vai para a auditoria. Na aba
    Clientes, `detalhado` põe as tarefas de cada cliente antes dos blocos, que ficam como o
    resumo."""
    state = await load_state(page, db, params)
    content, name = await render_pdf(page, db, state, detalhado=detalhado)
    await db.commit()
    return Response(content, media_type="application/pdf", headers=attachment(name))


async def render_pdf(
    page: LoggedPage, db: DB, state: State, *, detalhado: bool
) -> tuple[bytes, str]:
    """O PDF e o nome do arquivo (o do cliente, com um cliente só), já na auditoria e, na aba
    Clientes com um cliente só, no Histórico; quem chama faz o commit."""
    f, config = state.filters, state.choice.config
    if state.error or f is None:
        raise HTTPException(422, "Não foi possível gerar o PDF com estes filtros.")
    locale = page.locale
    now = format_datetime(locale, datetime.now(TIMEZONE))
    # O número da página, com os marcadores {n} e {total} (o `model_pdf` os preenche).
    numbering = page.t("relatorios.pdf.pagina")
    continued = page.t("relatorios.pdf.continua")  # com o marcador {titulo}
    period = page.t(
        "relatorios.pdf.periodo", de=format_date(locale, f.start), ate=format_date(locale, f.end)
    )
    # Com um cliente só no filtro, os blocos por cliente (a tabela, as barras dos maiores) teriam
    # só ele: ficam de fora.
    one_client = len(f.clients) == 1 and not f.no_client
    blocks = [b for b in config.blocks if not (one_client and b.dimension == "client")]
    found = await scope(page, db, state, blocks)
    views = [block_view(page, state, block, i, found) for i, block in enumerate(blocks)]
    # A descrição da aba, logo abaixo do cabeçalho; o período, o comparado e os filtros numa
    # linha só.
    when = [period]
    if compared_period := state.comparison():
        first, last = compared_period
        when.append(
            page.t(
                "relatorios.pdf.comparado",
                de=format_date(locale, first),
                ate=format_date(locale, last),
            )
        )
    when.append(_filters_line(page, state))
    lines = [description_of(page, state.choice), " · ".join(w for w in when if w)]
    if uses_overtime(blocks):  # o expediente usado, como na tela
        lines.append(await work_hours_line(page, db, state, f))
    colors = page.branding.colors
    light = palette(colors.model_dump() if colors else None)["light"]
    pdf_blocks = _pdf_blocks(page, views)
    table = "model"
    if detalhado and state.choice.slug == "clientes":
        # Os blocos, depois das tarefas, são o resumo (os cartões, que vêm primeiro, não têm
        # título).
        summary = pdf_blocks[0]
        if not summary.title:
            summary.title = page.t("relatorios.pdf.resumo")
        pdf_blocks = [*await _client_tasks(page, db, state, f), *pdf_blocks]
        table = "detailed"
    content = await run_in_threadpool(
        model_pdf.render_model,
        "",  # sem título: o nome da aba não vai para o PDF
        [line for line in lines if line],
        pdf_blocks,
        model_pdf.Page(page.t("relatorios.pdf.gerado", quando=now), numbering, continued),
        (light["primary"], light["chart-before"]),
        await get_report_logo(db),
        await get_letterhead(db),
    )
    reports_api.record_export(
        db, page.request, page.auth, f, format="pdf", table=table, model=state.choice.name
    )
    if state.choice.slug == "clientes" and one_client:
        # O Histórico e a cascata: com as datas do período (um relativo, como o mês atual, seria
        # outro depois), sem a cascata, que é da tela.
        again = {
            **state.query,
            "aba": "clientes",
            "periodo": builder.CUSTOM,
            "de": f.start.isoformat(),
            "ate": f.end.isoformat(),
            "dias": None,
            "origem": None,
            "cascata": None,
            "detalhado": "1" if table == "detailed" else None,
        }
        history.record(
            db,
            page.auth.user.id,
            f.clients[0].id,
            "detailed" if table == "detailed" else "simple",
            f.start,
            f.end,
            {k: v for k, v in again.items() if v},
        )
    name = f"relatorio-{f.start:%Y-%m-%d}-a-{f.end:%Y-%m-%d}.pdf"
    if one_client:  # com o nome do cliente
        name = f"{file_name(f.clients[0].label)} - {name}"
    return content, name


@router.get("/relatorios/csv")
async def block_csv(
    page: LoggedPageDep,
    db: DB,
    bloco: int,
    params: ParamsDep,
) -> Response:
    """O CSV de um bloco (docs/14 §14.8.4), com os filtros da tela; vai para a auditoria."""
    state = await load_state(page, db, params)
    f, config = state.filters, state.choice.config
    if state.error or f is None:
        raise HTTPException(422, "Não foi possível gerar o CSV com estes filtros.")
    if not 0 <= bloco < len(config.blocks):
        raise HTTPException(404)
    block = config.blocks[bloco]
    found = await scope(page, db, state, [block])
    result = builder.run(found.data, block, f.start, f.end)
    # Com a comparação, o bloco no período comparado, como na tela (sem a lista de tarefas e
    # sem as barras, que não comparam).
    previous = None
    if found.before is not None and found.comparison:
        first, last = found.comparison
        previous = builder.run(found.before, block, first, last)
    content = csv_export.render_block(found.data, result, cast(Locale, page.locale), previous)
    reports_api.record_export(
        db, page.request, page.auth, f, format="csv", table="block", model=state.choice.name
    )
    await db.commit()
    name = f"relatorio-bloco-{bloco + 1}-{f.start:%Y-%m-%d}-a-{f.end:%Y-%m-%d}.csv"
    return Response(
        content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/relatorios/chamados")
async def ticket_list(
    page: LoggedPageDep,
    db: DB,
    params: ParamsDep,
    medida: str,
    formato: str | None = None,
) -> Response:
    """Os chamados por trás de um número (detalhar, docs/14 §14.8.3), com os filtros da tela, e
    o CSV deles (`formato=csv`, que vai para a auditoria)."""
    if medida not in TICKET_SETS:
        raise HTTPException(404)
    measure = medida
    kind = TICKET_SETS[measure]
    state = await load_state(page, db, params)
    f = state.filters
    base = {**state.query, "aba": state.choice.slug}
    context: dict[str, Any] = {
        "title": page.t(f"relatorios.medidas.{measure}"),
        "kind": kind,
        "back": with_query("/relatorios", base),
        "interval": interval_text(page, state),
        "error": state.error,
        "rows": [],
        "count": 0,
        "csv": with_query("/relatorios/chamados", {**base, "medida": measure, "formato": "csv"}),
    }
    if f is None:
        if formato == "csv":
            raise HTTPException(422, "Não foi possível gerar o CSV com estes filtros.")
        context["error"] = state.error or page.t("relatorios.periodoInvalido")
        return page.render("reports/tickets.html", status_code=422, **context)

    # O conjunto da medida; nos concluídos, também o tempo líquido (uma coluna da lista).
    parts: set[service.Part] = {kind}
    if kind == "closed":
        parts.add("net_lead")
    data = await service.facts(db, page.auth, f, service.Want(rows=parts), state.lookups)
    tickets = builder.tickets_of(data, measure)
    # Os mais recentes primeiro; no em aberto, os mais antigos (os que esperam há mais tempo).
    if kind == "backlog":
        tickets.sort(key=lambda t: t.created_at)
    else:
        tickets.sort(key=lambda t: t.finished_at or t.created_at, reverse=True)
    if formato == "csv":
        content = csv_export.render_tickets(data, tickets, kind, cast(Locale, page.locale))
        reports_api.record_export(
            db, page.request, page.auth, f, format="csv", table="tickets", measure=measure
        )
        await db.commit()
        name = f"relatorio-chamados-{f.start:%Y-%m-%d}-a-{f.end:%Y-%m-%d}.csv"
        return Response(
            content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    def client(ticket: service.TicketFact) -> str:
        found = data.clients.get(ticket.client_id) if ticket.client_id else None
        return found.label if found else page.t("relatorios.semCliente")

    context["rows"] = [
        {
            "number": t.number,
            "title": t.title,
            "client": client(t),
            "team": data.teams[t.team_id].name,
            "status": data.statuses[t.status_id].name,
            "people": ", ".join(sorted(data.users[u].display_name for u in t.people)),
            "created_at": t.created_at,
            "finished_at": t.finished_at,
            "lead": format_elapsed(t.lead) if t.lead is not None else "—",
            "net_lead": format_elapsed(t.net_lead) if t.net_lead is not None else "—",
            "reopened": t.reopened,
            "age": format_elapsed(t.age) if t.age is not None else "—",
        }
        for t in tickets[:LISTED]
    ]
    context["count"] = len(tickets)
    return page.render("reports/tickets.html", **context)
