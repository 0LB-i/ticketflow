"""Relatórios (docs/14 §14.7 e §14.8): a tela, com os modelos prontos (Produtividade, Clientes,
Horas extras, Chamados) e os da pessoa em abas, cada um uma lista de blocos do construtor guiado
(`reports/builder.py`), os filtros e os downloads. Cada um vê o próprio trabalho; o supervisor, o
dos grupos que supervisiona; admin e auditor, tudo. Quem decide é o service
(`reports/service.resolve`), como na API: a tela não precisa de requires().

As outras partes: o estado que vem da URL em reports_state.py, os blocos prontos para a tela e
o PDF em reports_blocks.py, os downloads (PDF, CSV de um bloco, lista de chamados) em
reports_downloads.py e o editor de modelos em reports_editor.py.
"""

import unicodedata
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from chamados.db.session import DB
from chamados.modules.reports import builder, service
from chamados.modules.reports.builder import CUSTOM
from chamados.web.formatting import TIMEZONE, format_day
from chamados.web.page import LoggedPage, LoggedPageDep
from chamados.web.reports_blocks import (
    WEEKDAYS,
    block_view,
    client_preview,
    scopes,
    single_client,
    uses_overtime,
    wide,
)
from chamados.web.reports_state import (
    NO_CLIENT,
    RELATIVE_KEYS,
    TABS,
    Params,
    ParamsDep,
    Values,
    interval_text,
    last_months,
    load_state,
    origin_view,
    parse_uuids,
    with_query,
)

router = APIRouter()


# A tabela de cada modelo pronto de horas no CSV da API (`reports/csv_export.Table`); esses
# também têm o PDF.
CSV_TABLES = {"produtividade": "people", "clientes": "clients", "horas-extras": "overtime"}


def _fold(text: str) -> str:
    """Sem acento nem maiúsculas, para achar "Sem cliente" digitando "sem cli"."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


@router.get("/relatorios/clientes")
async def client_choices(
    page: LoggedPageDep, db: DB, q: str = "", cliente: Values = None
) -> HTMLResponse:
    """As opções do filtro de cliente (HTMX): "Sem cliente" e os clientes que batem com a busca,
    sem os já escolhidos (`cliente`, as etiquetas)."""
    text = q.strip()[:200]
    # No editor, as etiquetas do filtro de um bloco se chamam `b<i>-cliente`.
    extra = [v for k, v in page.request.query_params.multi_items() if k.endswith("-cliente")]
    chosen = [*(cliente or []), *extra]
    none_label = page.t("relatorios.semCliente")
    options = []
    if NO_CLIENT not in chosen and _fold(text) in _fold(none_label):
        options.append((NO_CLIENT, none_label))
    found = await service.client_choices(db, text, parse_uuids(chosen))
    options += [(str(c.id), c.name) for c in found]
    return page.render("reports/_client_options.html", options=options)


@router.get("/relatorios")
async def reports_page(page: LoggedPageDep, db: DB, params: ParamsDep) -> HTMLResponse:
    """A página sem os números: o título, as abas, os filtros e os downloads saem na hora, e um
    esqueleto do tamanho dos blocos pede `/relatorios/blocos` (hx-trigger="load")."""
    return await _report(page, db, params, lazy=True)


@router.get("/relatorios/blocos")
async def report_blocks(page: LoggedPageDep, db: DB, params: ParamsDep) -> HTMLResponse:
    """A mesma página, com os blocos calculados: o HTMX tira dela o #blocos (e quem está sem
    JavaScript chega aqui pelo link do <noscript>)."""
    return await _report(page, db, params, lazy=False)


async def _report(page: LoggedPage, db: DB, params: Params, *, lazy: bool) -> HTMLResponse:
    state = await load_state(page, db, params)
    choice, query, options = state.choice, state.query, state.options
    slug = choice.slug

    # As abas na ordem da pessoa, sem as escondidas; a escondida aberta pelo link aparece
    # enquanto está aberta. Os modelos prontos levam os filtros da tela; o da pessoa abre com os
    # que ele guarda.
    tab_names = {s: page.t(f"relatorios.abas.{key}") for s, key in TABS.items()}
    tab_names.update({str(m.public_id): m.name for m in state.models})
    tabs = [
        (
            s,
            tab_names[s],
            with_query("/relatorios", {**query, "aba": s} if s in TABS else {"aba": s}),
        )
        for s, shown in state.tabs
        if shown or s == slug
    ]
    # "Organizar abas": todas, com se aparecem e qual é a inicial (que não se esconde).
    arranged = [(s, tab_names[s], shown, s == state.initial) for s, shown in state.tabs]

    blocks: list[dict[str, Any]] = []
    downloads = None
    work_hours = None
    client_view = None
    # Na página sem os números: os blocos que o esqueleto imita (o índice, que é o id para onde
    # a paginação da lista rola, o visual e se ocupa a linha inteira).
    skeleton: list[tuple[int, str, bool]] | None = None
    f, config = state.filters, choice.config
    if f is not None and config is not None and config.audience == "client":
        # Sem um cliente (só um) no filtro, o aviso não depende dos números.
        if lazy and single_client(state) is not None:
            skeleton = [(0, "table", True)]
        else:
            client_view = await client_preview(page, db, state, f, config)
        if single_client(state) is not None:
            downloads = {"pdf": with_query("/relatorios/pdf", {**query, "aba": slug})}
    elif f is not None and config is not None and lazy:
        visuals = [b.visual for b in config.blocks]
        spans = wide(visuals, [b.width for b in config.blocks])
        skeleton = list(zip(range(len(visuals)), visuals, spans, strict=True))
    elif f is not None and config is not None:
        # A página de cada lista de tarefas (`pagina<i>`); sem ela, a primeira.
        numbers = page.request.query_params
        blocks = [
            block_view(
                page,
                state,
                config,
                block,
                i,
                scope,
                page_number=int(n)
                if (n := numbers.get(f"pagina{i}", "")).isascii() and n.isdigit() and len(n) <= 6
                else 1,
            )
            for i, (block, scope) in enumerate(
                zip(config.blocks, await scopes(page, db, state, config.blocks), strict=True)
            )
        ]
        spans = wide([b.visual for b in config.blocks], [b.width for b in config.blocks])
        for view, span in zip(blocks, spans, strict=True):
            view["wide"] = span
    if f is not None and config is not None and config.audience != "client":
        if uses_overtime(config):
            wh = state.lookups.work_hours
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

    # Os filtros de vários valores (etiquetas): nome, rótulo, opções, escolhidos, o texto de
    # "todos" e os nomes. Grupo só com o que escolher; pessoa, só para quem vê mais que o próprio
    # trabalho. O cliente não tem a lista (são milhares): busca pelo HTMX (`client_choices`), e
    # os nomes são só os dos escolhidos.
    client_names = {
        NO_CLIENT: page.t("relatorios.semCliente"),
        **{str(c): name for c, name in state.client_names.items()},
    }
    team_options = [(str(t.id), t.name) for t in options.teams]
    person_options = [(str(p.id), p.name) for p in options.people]
    status_options = [(str(s.id), s.name) for s in options.statuses]
    filters: list[tuple[str, str, list[tuple[str, str]] | None, Any, str, dict[str, str]]] = []
    if options.teams:
        filters.append(
            ("grupo", "grupo", team_options, query["grupo"], "todosOsGrupos", dict(team_options))
        )
    if len(options.people) > 1:
        filters.append(
            (
                "pessoa",
                "pessoa",
                person_options,
                query["pessoa"],
                "todasAsPessoas",
                dict(person_options),
            )
        )
    filters.append(("cliente", "cliente", None, query["cliente"], "todosOsClientes", client_names))
    filters.append(
        ("status", "status", status_options, query["status"], "todosOsStatus", dict(status_options))
    )

    # "Filtrado por": cada valor escolhido com o link que o tira, e "Limpar filtros", que tira
    # todos e mantém a aba e o período (sem nenhum filtro na URL valeriam os salvos do modelo).
    here = {**query, "aba": slug}
    names = {
        "grupo": dict(team_options),
        "pessoa": dict(person_options),
        "cliente": client_names,
        "status": dict(status_options),
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
            with_query(
                "/relatorios",
                {**here, "de": None, "ate": None, "dias": None, "origem": None, **back},
            ),
        )

    today = datetime.now(TIMEZONE).date()
    months = last_months(page.locale, today)
    start, end = state.start, state.end

    # Na impressão, no lugar das abas e dos filtros: o nome do modelo e o período.
    printed = None
    if start and end and start <= end:
        model_name = next(label for s, label, _ in tabs if s == slug)
        period_text = page.t(
            "relatorios.intervalo",
            de=format_day(page.locale, start),
            ate=format_day(page.locale, end),
        )
        printed = f"{model_name} · {period_text}"

    def period_url(first: date, last: date) -> str:
        """O endereço de um período: um mês da lista ou o personalizado."""
        month = next((m for m in months if (m.start, m.end) == (first, last)), None)
        period: dict[str, str | None]
        if month is None:
            period = {
                "periodo": CUSTOM,
                "de": first.isoformat(),
                "ate": last.isoformat(),
                "dias": None,
            }
        else:
            period = {"periodo": month.value, "de": None, "ate": None, "dias": None}
        return with_query("/relatorios", {**here, "origem": None, **period})

    def interval(first: date, last: date) -> str:
        return page.t(
            "relatorios.intervalo",
            de=format_day(page.locale, first),
            ate=format_day(page.locale, last),
        )

    # As setas andam um período do mesmo tamanho (o mês, o trimestre, os N dias). No "ano até
    # hoje", e num personalizado de 1º de janeiro até um dia do mesmo ano (que não seja o fim de
    # um mês: aí são meses inteiros), as mesmas datas do ano vizinho. Não vão além de hoje.
    steps = None
    if start and end and start <= end:
        year_to_date = state.period == "ano-ate-hoje" or (
            state.period == CUSTOM
            and (start.month, start.day) == (1, 1)
            and end.year == start.year
            and (end + timedelta(days=1)).day != 1
        )
        earlier = builder.previous_period(start, end, year_to_date=year_to_date)
        later = builder.next_period(start, end, year_to_date=year_to_date)
        steps = (
            (interval(*earlier), period_url(*earlier)),
            (interval(*later), period_url(*later) if later[0] <= today else None),
        )

    # Atalhos do personalizado: as semanas (segunda a domingo) e os meses, inteiros.
    monday = today - timedelta(days=today.weekday())
    shortcuts = [
        (page.t(f"relatorios.atalhos.{key}"), period_url(first, last))
        for key, (first, last) in (
            ("estaSemana", (monday, monday + timedelta(days=6))),
            ("semanaPassada", (monday - timedelta(days=7), monday - timedelta(days=1))),
            ("esteMes", (months[0].start, months[0].end)),
            ("mesPassado", (months[1].start, months[1].end)),
        )
    ]

    return page.render(
        "reports/index.html",
        tabs=tabs,
        tab=slug,
        arranged=arranged,
        # Depois de mover uma aba, o diálogo volta aberto; ao fechar, o endereço sem o pedido.
        organize=page.request.query_params.get("organizar") == "1",
        here_url=with_query("/relatorios", here),
        model=choice.model,
        period=state.period,
        period_groups=[
            (
                page.t("relatorios.periodosRelativos"),
                [(s, page.t(f"relatorios.periodos.{key}")) for s, key in RELATIVE_KEYS.items()],
            ),
            (
                page.t("relatorios.meses"),
                [(m.value, m.label) for m in months],
            ),
        ],
        start=state.start_text,
        end=state.end_text,
        days=state.days,
        period_ok=bool(start and end and start <= end),
        steps=steps,
        shortcuts=shortcuts,
        printed=printed,
        # O intervalo de um período relativo ou de um mês (que não aparece nos campos de data)
        # e o de comparação.
        interval=interval_text(page, state),
        query_compare=query["comparar"] or "",
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
        skeleton=skeleton,
        # A mesma consulta, inclusive a falta de filtros (que vale os salvos) e as páginas.
        blocks_url=f"/relatorios/blocos?{page.request.url.query}".rstrip("?"),
        client_view=client_view,
        work_hours=work_hours,
        error=state.error,
        warning=state.warning,
        downloads=downloads,
    )
