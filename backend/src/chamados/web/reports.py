"""Relatórios (docs/14 §14.7 e §14.8): a tela, com os modelos prontos (Produtividade, Clientes,
Horas extras, Chamados) e os da pessoa em abas, cada um uma lista de blocos do construtor guiado
(`reports/builder.py`), os filtros e os downloads. Cada um vê o próprio trabalho; o supervisor, o
dos grupos que supervisiona; admin e auditor, tudo. Quem decide é o service
(`reports/service.resolve`), como na API: a tela não precisa de requires().

As outras partes: o estado que vem da URL em reports_state.py, os blocos prontos para a tela e
o PDF em reports_blocks.py, os downloads (PDF, CSV de um bloco, lista de chamados) em
reports_downloads.py e o editor de modelos em reports_editor.py.
"""

from dataclasses import replace
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from chamados.db.session import DB
from chamados.modules.reports import builder, service
from chamados.web.formatting import TIMEZONE, format_day
from chamados.web.page import LoggedPageDep
from chamados.web.reports_blocks import block_view, client_preview, uses_overtime
from chamados.web.reports_state import (
    NO_CLIENT,
    RELATIVE_KEYS,
    TABS,
    ParamsDep,
    interval_text,
    last_months,
    load_state,
    origin_view,
    with_query,
)

router = APIRouter()


# A tabela de cada modelo pronto de horas no CSV da API (`reports/csv_export.Table`); esses
# também têm o PDF.
CSV_TABLES = {"produtividade": "people", "clientes": "clients", "horas-extras": "overtime"}


WEEKDAYS = ("seg", "ter", "qua", "qui", "sex", "sab", "dom")


@router.get("/relatorios")
async def reports_page(
    page: LoggedPageDep,
    db: DB,
    params: ParamsDep,
) -> HTMLResponse:
    state = await load_state(page, db, params)
    choice, query, options = state.choice, state.query, state.options
    slug = choice.slug

    # Os modelos prontos levam os filtros da tela; o da pessoa abre com os que ele guarda.
    tabs = [
        (s, page.t(f"relatorios.abas.{key}"), with_query("/relatorios", {**query, "aba": s}))
        for s, key in TABS.items()
    ] + [
        (str(m.public_id), m.name, with_query("/relatorios", {"aba": str(m.public_id)}))
        for m in state.models
    ]

    blocks: list[dict[str, Any]] = []
    downloads = None
    work_hours = None
    client_view = None
    f, config = state.filters, choice.config
    if f is not None and config is not None and config.audience == "client":
        client_view = await client_preview(page, db, state, f, config)
        if client_view["ready"]:
            downloads = {"pdf": with_query("/relatorios/pdf", {**query, "aba": slug})}
    elif f is not None and config is not None:
        data = await service.facts(db, page.auth, f)
        before = None
        if state.compare and any(b.visual == "cards" for b in config.blocks):
            first, last = builder.previous_period(
                f.start, f.end, year_to_date=state.period == "ano-ate-hoje"
            )
            before = await service.facts(db, page.auth, replace(f, start=first, end=last))
        blocks = [
            block_view(page, state, f, config, data, block, i, before)
            for i, block in enumerate(config.blocks)
        ]
        if uses_overtime(config):
            wh = data.work_hours
            work_hours = page.t(
                "relatorios.expedienteUsado",
                dias=", ".join(page.t(f"expediente.diasCurtos.{WEEKDAYS[d]}") for d in wh.weekdays),
                inicio=f"{wh.start:%H:%M}",
                fim=f"{wh.end:%H:%M}",
            )
        # Os downloads da API levam os mesmos filtros, com o idioma da pessoa (um link não
        # escolhe o Accept-Language). O PDF e a tabela da aba, só nos modelos prontos.
        api = {
            "start": f.start.isoformat(),
            "end": f.end.isoformat(),
            "team": query["grupo"],
            "person": query["pessoa"],
            "client": [str(c) for c in state.clients],
            "no_client": "true" if state.no_client else None,
            "status": query["status"],
            "locale": page.locale,
        }
        downloads = {"tarefas": with_query("/api/v1/reports/csv", {**api, "table": "tasks"})}
        if slug in CSV_TABLES and choice.model is None:
            downloads["pdf"] = with_query("/api/v1/reports/pdf", api)
            downloads["csv"] = with_query("/api/v1/reports/csv", {**api, "table": CSV_TABLES[slug]})
        else:  # o PDF do modelo, com os blocos (§14.8.6)
            downloads["pdf"] = with_query("/relatorios/pdf", {**query, "aba": slug})

    # "Salvar filtros": num modelo da pessoa, quando os da tela não são os guardados.
    filters_changed = False
    if choice.model is not None and config is not None and state.start and state.end:
        filters_changed = state.specs() != (config.period, config.filters)

    # Os filtros de vários valores (etiquetas): nome, rótulo, opções, escolhidos e o texto de
    # "todos". Grupo só com o que escolher; pessoa, só para quem vê mais que o próprio trabalho.
    filters = []
    if options.teams:
        team_options = [(str(t.id), t.name) for t in options.teams]
        filters.append(("grupo", "grupo", team_options, query["grupo"], "todosOsGrupos"))
    if len(options.people) > 1:
        person_options = [(str(p.id), p.name) for p in options.people]
        filters.append(("pessoa", "pessoa", person_options, query["pessoa"], "todasAsPessoas"))
    client_options = [(NO_CLIENT, page.t("relatorios.semCliente"))]
    client_options += [(str(c.id), c.name) for c in options.clients]
    filters.append(("cliente", "cliente", client_options, query["cliente"], "todosOsClientes"))
    status_options = [(str(s.id), s.name) for s in options.statuses]
    filters.append(("status", "status", status_options, query["status"], "todosOsStatus"))

    # "Filtrado por": cada valor escolhido com o link que o tira, e "Limpar filtros", que tira
    # todos e mantém a aba e o período (sem nenhum filtro na URL valeriam os salvos do modelo).
    here = {**query, "aba": slug}
    names = {
        "grupo": {str(t.id): t.name for t in options.teams},
        "pessoa": {str(p.id): p.name for p in options.people},
        "cliente": {
            NO_CLIENT: page.t("relatorios.semCliente"),
            **{str(c.id): c.name for c in options.clients},
        },
        "status": {str(s.id): s.name for s in options.statuses},
    }
    chosen = []
    for name, known in names.items():
        values = query[name] or []
        for value in values:
            without = with_query("/relatorios", {**here, name: [v for v in values if v != value]})
            chosen.append((known.get(value, value), without))
    clear_url = with_query("/relatorios", {k: v for k, v in here.items() if k not in names})

    # A trilha do detalhar: o período clicado e o link que volta ao de antes.
    drilled = None
    origin = origin_view(page, state)
    if origin is not None and state.start and state.end:
        label, back = origin
        drilled = (
            page.t(
                "relatorios.detalhe.periodo",
                de=format_day(page.locale, state.start),
                ate=format_day(page.locale, state.end),
            ),
            page.t("relatorios.detalhe.voltar", periodo=label),
            with_query("/relatorios", {**here, "de": None, "ate": None, "origem": None, **back}),
        )

    today = datetime.now(TIMEZONE).date()
    start, end = state.start, state.end
    return page.render(
        "reports/index.html",
        tabs=tabs,
        tab=slug,
        model=choice.model,
        period=state.period,
        period_groups=[
            (
                page.t("relatorios.periodosRelativos"),
                [(s, page.t(f"relatorios.periodos.{key}")) for s, key in RELATIVE_KEYS.items()],
            ),
            (
                page.t("relatorios.meses"),
                [(m.value, m.label) for m in last_months(page.locale, today)],
            ),
        ],
        start=state.start_text,
        end=state.end_text,
        period_ok=bool(start and end and start <= end),
        # O intervalo de um período relativo ou de um mês (que não aparece nos campos de data)
        # e o de comparação.
        interval=interval_text(page, state),
        compare=state.compare,
        filters=filters,
        query_fields=[
            (name, value)
            for name, values in query.items()
            if values
            for value in ([values] if isinstance(values, str) else values)
        ],
        filters_changed=filters_changed,
        # Volta aos filtros salvos: o modelo sem nenhum filtro na URL.
        restore_url=with_query("/relatorios", {"aba": slug}),
        chosen=chosen,
        clear_url=clear_url,
        drilled=drilled,
        origin=state.origin,
        new_model_url=with_query("/relatorios/modelos/novo", {**query, "base": slug}),
        blocks=blocks,
        client_view=client_view,
        work_hours=work_hours,
        error=state.error,
        warning=state.warning,
        downloads=downloads,
    )
