"""Relatórios: os downloads da tela (docs/14 §14.8.4 a §14.8.6), com os mesmos filtros e o
idioma da pessoa: o PDF de um modelo (ou o relatório para o cliente), o CSV de um bloco e a lista
dos chamados por trás de um número (detalhar), com o CSV dela. Todo download vai para a
auditoria (`report.exported`).
"""

import base64
from collections.abc import Callable
from datetime import datetime
from typing import Any, cast

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from chamados.core.i18n import Locale
from chamados.db.session import DB
from chamados.modules.reports import builder, csv_export, model_pdf, service
from chamados.modules.reports import router as reports_api
from chamados.modules.reports.builder import CHARTS, ELAPSED, TICKET_SETS
from chamados.modules.system.service import get_value
from chamados.web.formatting import TIMEZONE, format_date, format_datetime, format_elapsed
from chamados.web.page import LoggedPage, LoggedPageDep
from chamados.web.palette import palette
from chamados.web.reports_blocks import (
    LISTED,
    Format,
    Point,
    block_view,
    client_preview,
    scopes,
)
from chamados.web.reports_state import ParamsDep, State, interval_text, load_state, with_query

router = APIRouter()

# A altura escolhida no bloco (`Block.height`) sobre a média, como na tela (h-28, h-40, h-56).
SCALE = {"s": 0.7, "m": 1.0, "l": 1.4}


def _ticks(points: list[Point], step: int, fmt: Format) -> list[tuple[int, str]]:
    """As marcas do eixo, como as do _charts.html: o topo, a metade e o zero."""
    highest = max((max(p.value, p.before or 0, p.extra) for p in points), default=0)
    top = max(step, -(-highest // step) * step)
    return [(top, fmt(top)), (top // 2, fmt(top // 2)), (0, fmt(0))]


def _pdf_blocks(page: LoggedPage, views: list[dict[str, Any]]) -> list[model_pdf.Block]:
    """Os blocos da tela, já formatados, no formato do PDF."""
    blocks: list[model_pdf.Block] = []
    for v in views:
        visual = v["visual"]
        # O período e o filtro próprios do bloco, quando ele tem, debaixo do título.
        # O aviso do filtro do bloco que deixou de valer vai junto.
        subtitle = " · ".join(p for p in (v["period"], v["warning"]) if p) if v["own"] else ""
        if "message" in v:  # o filtro do bloco não combina com o da tela
            blocks.append(model_pdf.Grid(v["title"], [], [], empty=v["message"], subtitle=subtitle))
        elif visual == "cards":
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
                if card.get("hint"):
                    note = f"{note} · {card['hint']}" if note else card["hint"]
                items.append((card["label"], card["value"], note))
            blocks.append(
                model_pdf.Cards(v["title"], items, big=v.get("big", False), subtitle=subtitle)
            )
        elif visual in CHARTS:
            fmt = v["fmt"]
            blocks.append(
                model_pdf.Chart(
                    v["title"],
                    visual,
                    [(p.label, p.value, p.extra, fmt(p.value)) for p in v["points"]],
                    ticks=_ticks(v["points"], v["step"], fmt),
                    legend=v.get("labels") or v.get("legend"),
                    empty=v.get("empty", ""),
                    before=[p.before for p in v["points"]] if "legend" in v else [],
                    reference=v.get("reference"),
                    area=v.get("area", False),
                    subtitle=subtitle,
                    scale=SCALE[v["height"]],
                    color=v["color"],
                )
            )
        elif visual == "heatmap":
            blocks.append(
                model_pdf.Heatmap(
                    v["title"],
                    v["hours"],
                    [(short, [c["level"] for c in cells]) for short, _, cells in v["days"]],
                    v["legend"],
                    empty=v["empty"],
                    subtitle=subtitle,
                    scale=SCALE[v["height"]],
                )
            )
        elif visual == "table":
            # As fontes padrão do PDF não têm o Δ: a coluna da variação vira uma abreviatura.
            delta = page.t("relatorios.comparacao.colunaPdf")
            columns = [
                delta if title else c for c, title in zip(v["columns"], v["titles"], strict=True)
            ]
            blocks.append(
                model_pdf.Grid(
                    v["title"],
                    columns,
                    [[label, *(text for text, _ in cells)] for label, _, cells in v["rows"]],
                    total=[text for text, _ in v["total"]],
                    total_label=v["total_label"],
                    empty=page.t("relatorios.nada"),
                    subtitle=subtitle,
                )
            )
        else:
            # As colunas escolhidas no bloco, como na tela; o chamado é o número e o título.
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
                    subtitle=subtitle,
                )
            )
    return blocks


def _filters_line(page: LoggedPage, state: State) -> str:
    """Os filtros usados, para o cabeçalho do PDF."""
    o = state.options
    parts = []
    for key, chosen in (
        ("grupo", [t.name for t in o.teams if t.id in state.teams]),
        ("pessoa", [p.name for p in o.people if p.id in state.people]),
        (
            "cliente",
            ([page.t("relatorios.semCliente")] if state.no_client else [])
            + sorted(
                (state.client_names[c] for c in state.clients if c in state.client_names),
                key=str.casefold,
            ),
        ),
        ("status", [s.name for s in o.statuses if s.id in state.statuses]),
    ):
        if chosen:
            parts.append(f"{page.t(f'relatorios.{key}')}: {', '.join(chosen)}")
    return " · ".join(parts)


@router.get("/relatorios/pdf")
async def report_pdf(page: LoggedPageDep, db: DB, params: ParamsDep) -> Response:
    """O PDF do modelo aberto (§14.8.6) ou, num modelo para o cliente, o relatório para ele
    (§14.8.5); com os filtros da tela, e vai para a auditoria."""
    state = await load_state(page, db, params)
    f, config = state.filters, state.choice.config
    if state.error or f is None or config is None:
        raise HTTPException(422, "Não foi possível gerar o PDF com estes filtros.")
    locale = page.locale
    now = format_datetime(locale, datetime.now(TIMEZONE))
    period = page.t(
        "relatorios.pdf.periodo", de=format_date(locale, f.start), ate=format_date(locale, f.end)
    )
    if config.audience == "client":
        view = await client_preview(page, db, state, f, config)
        if not view["ready"]:
            raise HTTPException(422, "O relatório do cliente precisa de um cliente (só um).")
        stored = await get_value(db, "logo")
        logo = base64.b64decode(stored["data"]) if stored else None
        content = await run_in_threadpool(
            model_pdf.render_client,
            logo,
            view["title"],
            view["lines"],
            view["totals"],
            model_pdf.Grid("", view["columns"], view["rows"], empty=page.t("relatorios.nada")),
            view["footer"],
        )
        table = "client"
    else:
        found = await scopes(page, db, state, config.blocks)
        views = [
            block_view(page, state, config, block, i, scope)
            for i, (block, scope) in enumerate(zip(config.blocks, found, strict=True))
        ]
        lines = [period]
        if compared_period := state.comparison():
            first, last = compared_period
            lines.append(
                page.t(
                    "relatorios.pdf.comparado",
                    de=format_date(locale, first),
                    ate=format_date(locale, last),
                )
            )
        lines.append(_filters_line(page, state))
        colors = page.branding.colors
        light = palette(colors.model_dump() if colors else None)["light"]
        # As séries do modo claro, pelo nome do token (a `chart-1` é a primary).
        series = {
            "chart-1": light["primary"],
            **{t: light[t] for t in ("chart-2", "chart-3", "chart-4", "chart-before")},
        }
        heat = tuple(light[f"heat-{k}"] for k in range(1, 6))
        content = await run_in_threadpool(
            model_pdf.render_model,
            state.choice.name,
            [line for line in lines if line],
            _pdf_blocks(page, views),
            page.t("relatorios.pdf.gerado", quando=now, quem=page.auth.user.display_name),
            series,
            heat,
        )
        table = "model"
    reports_api.record_export(
        db, page.request, page.auth, f, format="pdf", table=table, model=state.choice.name
    )
    await db.commit()
    name = f"relatorio-{f.start:%Y-%m-%d}-a-{f.end:%Y-%m-%d}.pdf"
    return Response(
        content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


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
    if state.error or f is None or config is None:
        raise HTTPException(422, "Não foi possível gerar o CSV com estes filtros.")
    if not 0 <= bloco < len(config.blocks):
        raise HTTPException(404)
    block = config.blocks[bloco]
    # O período e os filtros do bloco (os próprios, quando ele tem), como na tela.
    (scope,) = await scopes(page, db, state, [block])
    if scope.filters is None or scope.data is None:
        raise HTTPException(422, "Não foi possível gerar o CSV com estes filtros.")
    f = scope.filters
    result = builder.run(scope.data, block, f.start, f.end)
    # Com a comparação, o bloco no período comparado, como na tela (sem a lista de tarefas e
    # sem as barras e as empilhadas, que não comparam).
    previous = None
    if scope.before is not None and scope.comparison:
        first, last = scope.comparison
        previous = builder.run(scope.before, block, first, last)
    content = csv_export.render_block(
        scope.data,
        result,
        cast(Locale, page.locale),
        previous,
        block.decimals,
        block.columns or builder.CSV_COLUMNS,
    )
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
    agregacao: str | None = None,
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
        "title": page.t(
            f"relatorios.medias.{measure}"
            if agregacao == "media" and measure in ELAPSED
            else f"relatorios.medidas.{measure}"
        ),
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
