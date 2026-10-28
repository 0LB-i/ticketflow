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
from chamados.modules.reports import history, saved, service
from chamados.modules.reports.builder import CUSTOM
from chamados.modules.reports.models import ReportModel
from chamados.web.formatting import TIMEZONE, format_date, format_datetime, format_day
from chamados.web.page import LoggedPage, LoggedPageDep
from chamados.web.reports_blocks import (
    block_view,
    client_preview,
    scopes,
    single_client,
    wide,
)
from chamados.web.reports_state import (
    NO_CLIENT,
    RELATIVE_KEYS,
    TABS,
    Params,
    ParamsDep,
    Values,
    closed_statuses,
    interval_text,
    last_months,
    load_state,
    origin_view,
    parse_uuids,
    with_query,
)

router = APIRouter()


# A tabela de cada modelo pronto de horas no CSV da API (`reports/csv_export.Table`).
CSV_TABLES = {"produtividade": "people", "clientes": "clients", "horas-extras": "overtime"}


def _fold(text: str) -> str:
    """Sem acento nem maiúsculas, para achar "Sem cliente" digitando "sem cli"."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


@router.get("/relatorios/clientes")
async def client_choices(
    page: LoggedPageDep, db: DB, q: str = "", cliente: Values = None, cascata: bool = False
) -> HTMLResponse:
    """As opções do filtro de cliente (HTMX): "Sem cliente" e os clientes que batem com a busca,
    sem os já escolhidos (`cliente`, as etiquetas) e, na cascata da aba Clientes, sem os que já
    tiveram relatório da pessoa hoje."""
    text = q.strip()[:200]
    # No editor, as etiquetas do filtro de um bloco se chamam `b<i>-cliente`.
    extra = [v for k, v in page.request.query_params.multi_items() if k.endswith("-cliente")]
    chosen = [*(cliente or []), *extra]
    none_label = page.t("relatorios.semCliente")
    options = []
    if NO_CLIENT not in chosen and _fold(text) in _fold(none_label):
        options.append((NO_CLIENT, none_label))
    done = await history.clients_today(db, page.auth.user.id) if cascata else []
    found = await service.client_choices(db, text, [*parse_uuids(chosen), *done])
    options += [(str(c.id), c.name) for c in found]
    return page.render("reports/_client_options.html", options=options)


def _tab_names(
    page: LoggedPage, models: list[ReportModel]
) -> tuple[dict[str, str], dict[str, str]]:
    """O nome de cada aba e a dica: a descrição; a dos modelos da pessoa, como foi salva (sem
    converter a configuração de cada um)."""
    names = {s: page.t(f"relatorios.abas.{key}") for s, key in TABS.items()}
    names.update({str(m.public_id): m.name for m in models})
    tips = {s: page.t(f"relatorios.descricoes.{key}") for s, key in TABS.items()}
    for m in models:
        tip = m.config.get("description")
        tips[str(m.public_id)] = tip if isinstance(tip, str) else ""
    return names, tips


@router.get("/relatorios/historico")
async def history_page(page: LoggedPageDep, db: DB) -> HTMLResponse:
    """O Histórico (docs/14 §14.7): os PDFs da aba Clientes que a pessoa baixou com um cliente
    só, com o link que gera o mesmo de novo. As abas, na ordem da pessoa, sem os filtros."""
    auth = page.auth
    models = await saved.list_mine(db, auth)
    default = next((str(m.public_id) for m in models if m.is_default), None)
    arranged = saved.arrange(
        [*TABS, *(str(m.public_id) for m in models)], default, await saved.tab_prefs(db, auth)
    )
    names, tips = _tab_names(page, models)
    found = await history.entries(db, auth.user.id)
    return page.render(
        "reports/history.html",
        tabs=[
            (s, names[s], with_query("/relatorios", {"aba": s}), tips[s])
            for s, shown in arranged
            if shown
        ],
        entries=[
            {
                "when": format_datetime(page.locale, e.created_at),
                "client": e.client,
                "period": page.t(
                    "relatorios.detalhe.intervalo",
                    de=format_date(page.locale, e.start),
                    ate=format_date(page.locale, e.end),
                ),
                "kind": page.t(f"relatorios.historico.tipos.{e.kind}"),
                "url": with_query("/relatorios/pdf", e.query),
            }
            for e in found
        ],
        listed=history.LISTED,
    )


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
    tab_names, tips = _tab_names(page, state.models)

    def tab_query(s: str) -> dict[str, Any]:
        if s not in TABS:
            return {"aba": s}
        # A aba Clientes, sem um status na tela, abre com os concluídos (o filtro dela).
        if s == "clientes" and not query["status"]:
            return {**query, "aba": s, "status": closed_statuses(state.lookups)}
        return {**query, "aba": s}

    tabs = [
        (s, tab_names[s], with_query("/relatorios", tab_query(s)), tips[s])
        for s, shown in state.tabs
        if shown or s == slug
    ]
    # "Organizar abas": todas, com se aparecem e qual é a inicial (que não se esconde).
    arranged = [(s, tab_names[s], shown, s == state.initial) for s, shown in state.tabs]

    blocks: list[dict[str, Any]] = []
    downloads = None
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
        # Os CSV da API levam os mesmos filtros, com o idioma da pessoa (um link não escolhe o
        # Accept-Language). A tabela da aba, só nos modelos prontos de horas.
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
        # O PDF é sempre o do modelo, com os blocos (§14.8.6), inclusive nos prontos de horas. Na
        # aba Clientes, ele é o simplificado, e o detalhado traz antes as tarefas de cada cliente.
        pdf = with_query("/relatorios/pdf", {**query, "aba": slug})
        downloads = {"tarefas": with_query("/api/v1/reports/csv", {**api, "table": "tasks"})}
        if slug == "clientes" and choice.model is None:
            downloads["simplificado"] = pdf
            downloads["detalhado"] = with_query(
                "/relatorios/pdf", {**query, "aba": slug, "detalhado": "1"}
            )
        else:
            downloads["pdf"] = pdf
        if slug in CSV_TABLES and choice.model is None:
            downloads["csv"] = with_query("/api/v1/reports/csv", {**api, "table": CSV_TABLES[slug]})

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
        model_name = next(label for s, label, _, _ in tabs if s == slug)
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
        shortcuts=shortcuts,
        printed=printed,
        # O intervalo de um período relativo ou de um mês (que não aparece nos campos de data)
        # e o de comparação.
        interval=interval_text(page, state),
        query_compare=query["comparar"] or "",
        # Na aba Clientes, a escolha da hora extra ("" é sem separação).
        query_extras=(query["extras"] or "") if slug == "clientes" and not choice.model else None,
        # Com um cliente só, as horas descontadas do excedente.
        query_discount=(query["desconto"] or "") if state.discount_field else None,
        query_cascade=state.cascade if slug == "clientes" and not choice.model else None,
        clients_url="/relatorios/clientes?cascata=1" if state.cascade else "/relatorios/clientes",
        discount_invalid=state.discount_invalid,
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
        error=state.error,
        warning=state.warning,
        downloads=downloads,
    )
