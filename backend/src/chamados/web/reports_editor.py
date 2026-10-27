"""Relatórios: o editor de um modelo pessoal (docs/14 §14.8.1 e §14.8.3) e o "Salvar filtros".

O formulário tem os campos de cada bloco (`b<i>-visual`, `b<i>-agrupar`, `b<i>-medida(s)`…), lidos
de `request.form()`. Adicionar, remover, mover e mudar as escolhas de um bloco refazem o
formulário pelo HTMX, sem salvar; só `acao=salvar` grava. O modelo novo leva o período e os
filtros da tela, em campos escondidos. Cada bloco mostra a prévia, calculada como na tela.
"""

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.datastructures import FormData

from chamados.db.session import DB
from chamados.modules.reports import builder, saved, service
from chamados.modules.reports.builder import (
    BUILTINS,
    CATEGORIES,
    CHARTS,
    CLIENT_COLUMNS,
    COLORED,
    DEFAULT_DAYS,
    LAST_DAYS,
    REFERENCED,
    SERIES,
    SIZED,
    Block,
    BlockPeriod,
    ClientSpec,
    FilterSpec,
    PdfSpec,
    PeriodSpec,
    ReportConfig,
)
from chamados.modules.reports.models import ReportModel
from chamados.web.formatting import TIMEZONE, format_day
from chamados.web.page import LoggedPage, LoggedPageDep, check_csrf
from chamados.web.reports_blocks import (
    CLIENT_COLUMN_KEYS,
    TASK_COLUMN_KEYS,
    block_title,
    block_view,
    scopes,
)
from chamados.web.reports_state import (
    FILTER_FIELDS,
    NO_CLIENT,
    RELATIVE_KEYS,
    Params,
    ParamsDep,
    form_params,
    load_state,
    parse_days,
    parse_uuids,
    with_query,
)

router = APIRouter()


@router.post("/relatorios/modelos/{model_id}/filtros")
async def save_filters(
    page: LoggedPageDep,
    db: DB,
    model_id: uuid.UUID,
) -> Response:
    """Guarda no modelo o período e os filtros da tela."""
    form = await page.request.form()
    check_csrf(page, str(form.get("csrf_token", "")))
    model = await saved.get(db, page.auth, model_id)
    state = await load_state(page, db, replace(form_params(form), aba=str(model_id)))
    response = RedirectResponse(with_query("/relatorios", {"aba": str(model_id)}), status_code=303)
    if state.error or state.choice.config is None:
        page.flash(response, ("error", state.error or page.t("comum.erroInesperado")))
        return response
    period, filters = state.specs()
    await saved.save_filters(
        db, model, state.choice.config.model_copy(update={"period": period, "filters": filters})
    )
    await db.commit()
    page.flash(response, ("success", page.t("relatorios.filtrosSalvos")))
    return response


@router.post("/relatorios/abas")
async def organize_tabs(page: LoggedPageDep, db: DB) -> Response:
    """Organizar abas: a ordem (`ordem`, as abas na ordem do diálogo) e as que aparecem
    (`mostrar`) entram na preferência da pessoa. `acao` sobe ou desce uma aba (`subir-<k>`,
    `descer-<k>`, pela posição) e o diálogo volta aberto; `salvar` só grava. Um id que não é aba
    da pessoa (um modelo de outra) responde como os modelos: 404."""
    form = await page.request.form()
    check_csrf(page, str(form.get("csrf_token", "")))
    models = await saved.list_mine(db, page.auth)
    known = [*BUILTINS, *(str(m.public_id) for m in models)]
    order = list(dict.fromkeys(v for v in form.getlist("ordem") if isinstance(v, str)))
    shown = {v for v in form.getlist("mostrar") if isinstance(v, str)}
    if not (set(order) | shown) <= set(known):
        raise HTTPException(404, "Modelo não encontrado.")
    action = str(form.get("acao", "salvar"))
    verb, _, number = action.partition("-")
    moved = verb in ("subir", "descer") and number.isascii() and number.isdigit()
    if moved and len(number) <= 2:
        i = int(number)
        j = i - 1 if verb == "subir" else i + 1
        if 0 <= i < len(order) and 0 <= j < len(order):
            order[i], order[j] = order[j], order[i]
    # O inicial não se esconde: o modelo marcado como inicial ou, sem ele, a primeira aba.
    default = next((str(m.public_id) for m in models if m.is_default), None)
    initial = default or (order or known)[0]
    hidden = [i for i in order if i not in shown and i != initial]
    await saved.save_tabs(db, page.auth, saved.TabPrefs(order=order, hidden=hidden))
    await db.commit()
    back = form_params(form)
    query: dict[str, Any] = {name: getattr(back, name) for name in FILTER_FIELDS}
    aba = form.get("aba")
    query["aba"] = aba if isinstance(aba, str) else None
    query["organizar"] = "1" if moved else None
    response = RedirectResponse(with_query("/relatorios", query), status_code=303)
    page.flash(response, ("success", page.t("relatorios.abasSalvas")))
    return response


TOPPED = ("bars", "columns", "stacked", "table")  # os que oferecem só os N maiores
NEW_BLOCK = Block(visual="table", dimension="person", measures=["hours"])


@dataclass
class EditorForm:
    name: str = ""
    description: str = ""
    hours: str = "hm"
    is_default: bool = False
    audience: str = "internal"  # ou "client": o relatório para o cliente (§14.8.5)
    show_people: bool = False
    client: ClientSpec = field(default_factory=ClientSpec)
    pdf: PdfSpec = field(default_factory=PdfSpec)
    blocks: list[Block] = field(default_factory=list)
    errors: dict[int, str] = field(default_factory=dict)  # bloco → erro
    error: str | None = None


def _read_block(form: FormData, i: int) -> Block:
    """Um bloco do formulário. As escolhas que não cabem no visual (ex.: depois de trocá-lo) se
    ajustam: o agrupamento vai para um que ele aceita e a medida passa de uma para várias."""

    def one(name: str) -> str:
        value = form.get(f"b{i}-{name}")
        return value.strip() if isinstance(value, str) else ""

    visual: builder.Visual = next((v for v in builder.VISUALS if v == one("visual")), "table")
    # O agrupamento e as medidas ficam entre os que o visual aceita (`builder.dimensions_for`,
    # `measures_for`); fora deles, o primeiro que cabe (nos gráficos de tempo, o dia).
    allowed = builder.dimensions_for(visual)
    dimension = next((d for d in allowed if d == one("agrupar")), None)
    if dimension is None and allowed:
        default = "day" if visual in ("columns", "stacked", "line") else "person"
        dimension = next((d for d in allowed if d == default), allowed[0])
    offered = builder.measures_for(visual, dimension)
    single = one("medida")
    checked = [v for v in form.getlist(f"b{i}-medidas") if isinstance(v, str)]
    # Na ordem guardada (`b<i>-sequencia`, a das colunas da tabela e dos cartões, que as setas
    # mudam); as marcadas agora entram no fim, na ordem do catálogo.
    sequence = [v for v in form.getlist(f"b{i}-sequencia") if isinstance(v, str)]
    measures = list(
        dict.fromkeys(
            [m for m in sequence if m in checked and m in offered]
            + [m for m in offered if m in checked]
        )
    )
    if visual == "stacked":
        measures = list(offered)
    elif visual == "combo":
        # As barras e a linha: duas medidas da mesma unidade (a da linha, entre as que cabem).
        first = single if single in offered else (measures or list(offered))[0]
        partners = [m for m in offered if m != first and builder.unit(m) == builder.unit(first)]
        second = one("medida2")
        measures = [first, second if second in partners else partners[0]] if partners else [first]
    elif visual in (*CHARTS, "heatmap"):
        chosen = single if single in offered else (measures or list(offered))[0]
        measures = [chosen]
    elif not measures and single in offered:
        measures = [single]
    top = one("maiores")
    order = one("ordem")
    # O período próprio: um relativo da lista (vazio é o da tela), com os N dias no
    # "ultimos-n-dias"; o filtro próprio, as etiquetas (sem nenhuma, o da tela).
    kind = next((k for k in builder.RELATIVE if k == one("periodo")), None)
    period = None
    if kind is not None:
        days = (parse_days(one("dias")) or DEFAULT_DAYS) if kind == LAST_DAYS else None
        period = BlockPeriod(kind=kind, days=days)

    def many(name: str) -> list[str]:
        return [v for v in form.getlist(f"b{i}-{name}") if isinstance(v, str)]

    own = FilterSpec(
        teams=parse_uuids(many("grupo")),
        people=parse_uuids(many("pessoa")),
        clients=parse_uuids(many("cliente")),
        no_client=NO_CLIENT in many("cliente"),
        statuses=list(
            dict.fromkeys(
                int(v) for v in many("status") if v.isascii() and v.isdigit() and len(v) <= 5
            )
        ),
    )
    # Só os maiores, nos agrupamentos por cadastro (os períodos, os ciclos e a idade são fixos).
    cut = None
    if (
        visual in TOPPED
        and dimension in CATEGORIES
        and top.isascii()
        and top.isdigit()
        and len(top) <= 3
    ):
        cut = min(int(top), 100) or None
    columns = None
    if visual == "tasks":
        marked = form.getlist(f"b{i}-colunas")
        columns = [c for c in builder.TASK_COLUMNS if c in marked]
    timed = visual == "tasks" or bool(set(measures) & set(builder.DURATIONS))
    fractional = timed or bool(set(measures) & {*builder.PERCENT, *builder.RATES})
    return Block(
        visual=visual,
        title=one("titulo")[:120],
        dimension=dimension,
        measures=measures,
        top=cut,
        hide_others=cut is not None and one("semOutros") == "1",
        order=order if order in ("desc", "asc", "name") else "desc",
        only_overtime=one("extras") == "1",
        # A média só nos tempos até a conclusão: sem eles, volta à mediana.
        aggregate="mean"
        if one("agregacao") == "mean" and set(measures) & set(builder.ELAPSED)
        else "median",
        area=visual == "line" and one("area") == "1",
        big=visual == "cards" and len(measures) == 1 and one("grande") == "1",
        reference=next(
            (r for r in ("mean", "median") if r == one("referencia") and visual in REFERENCED),
            "none",
        ),
        period=period,
        filters=own if own != FilterSpec() else None,
        width=next((w for w in ("half", "full") if w == one("largura")), None),
        # A altura só nos que a têm; fora deles (ex.: depois de trocar o visual), a média.
        height=next((h for h in ("s", "l") if h == one("altura") and visual in SIZED), "m"),
        # A cor da série, das que a paleta tem; vazia (ou fora deles), a da instalação.
        color=next((c for c in SERIES if c == one("cor") and visual in COLORED), None),
        # O formato das horas e as casas, só onde valem (`check_block`); vazios, os de sempre.
        hours=next((h for h in ("hm", "decimal") if h == one("horas") and timed), None),
        decimals=next((d for d in (0, 1, 2) if str(d) == one("casas") and fractional), None),
        # As colunas da lista de tarefas, na ordem fixa; as de sempre (ou nenhuma) ficam None.
        columns=columns if columns and tuple(columns) != builder.DEFAULT_COLUMNS else None,
        # Marcado "Deixar fora do PDF" (o padrão, sem o campo, é ficar no PDF).
        in_pdf=one("foraDoPdf") != "1",
    )


def _free_text(form: FormData, name: str, limit: int) -> str:
    """Um texto livre de várias linhas (as quebras do navegador viram "\n")."""
    return str(form.get(name, "")).replace("\r\n", "\n").strip()[:limit]


def _read_editor(form: FormData) -> tuple[EditorForm, str]:
    count = form.get("blocos")
    valid = isinstance(count, str) and count.isascii() and count.isdigit() and len(count) <= 2
    total = min(int(count), 12) if valid else 0  # type: ignore[arg-type]
    hours = form.get("horas")
    editor = EditorForm(
        name=str(form.get("nome", "")),
        description=str(form.get("descricao", "")).strip()[:200],
        hours=hours if hours in ("hm", "decimal") else "hm",
        is_default=form.get("inicial") == "1",
        audience="client" if form.get("publico") == "client" else "internal",
        show_people=form.get("atendeu") == "1",
        # O relatório para o cliente: os textos, as colunas (nenhuma marcada: as de sempre) e as
        # horas (marcado "Esconder as horas"; sem o campo, elas aparecem).
        client=ClientSpec(
            intro=_free_text(form, "cliente-abertura", 1000),
            notes=_free_text(form, "cliente-observacoes", 1000),
            columns=[c for c in CLIENT_COLUMNS if c in form.getlist("cliente-colunas")]
            or list(CLIENT_COLUMNS),
            show_hours=form.get("cliente-semHoras") != "1",
        ),
        pdf=PdfSpec(
            orientation="landscape" if form.get("pdf-orientacao") == "landscape" else "portrait",
            title=str(form.get("pdf-titulo", "")).strip()[:120],
            footer=str(form.get("pdf-rodape", "")).strip()[:200],
        ),
        blocks=[_read_block(form, i) for i in range(total)],
    )
    return editor, str(form.get("acao", "salvar"))


def _apply(editor: EditorForm, action: str) -> None:
    """Adicionar, remover e mover blocos (o formulário volta sem salvar)."""
    blocks = editor.blocks
    if action == "adicionar" and len(blocks) < 12:
        blocks.append(NEW_BLOCK.model_copy())
        return
    # Mover uma medida dentro do bloco: "medida-subir-<bloco>-<medida>" (ou descer).
    parts = action.split("-")
    if (
        len(parts) == 4
        and parts[0] == "medida"
        and all(p.isascii() and p.isdigit() and len(p) <= 2 for p in parts[2:])
    ):
        i, j = int(parts[2]), int(parts[3])
        if i < len(blocks):
            measures = list(blocks[i].measures)
            k = j - 1 if parts[1] == "subir" else j + 1
            if 0 <= j < len(measures) and 0 <= k < len(measures):
                measures[j], measures[k] = measures[k], measures[j]
                blocks[i] = blocks[i].model_copy(update={"measures": measures})
        return
    verb, _, number = action.partition("-")
    if not (number.isascii() and number.isdigit() and len(number) <= 2) or int(number) >= len(
        blocks
    ):
        return
    i = int(number)
    if verb == "remover":
        del blocks[i]
    elif verb == "subir" and i > 0:
        blocks[i - 1], blocks[i] = blocks[i], blocks[i - 1]
    elif verb == "descer" and i < len(blocks) - 1:
        blocks[i + 1], blocks[i] = blocks[i], blocks[i + 1]


@dataclass
class Previews:
    """A prévia de cada bloco: o bloco pronto para o template (`reports_blocks.block_view`) ou,
    num bloco inválido ou sem período, o erro; `label`, o título com o período usado."""

    blocks: list[dict[str, Any] | str] = field(default_factory=list)
    label: str = ""


async def _previews(page: LoggedPage, db: DB, editor: EditorForm, params: Params) -> Previews:
    """A prévia dos blocos com o período e os filtros da tela (modelo novo, pelos campos
    escondidos) ou os salvos (ao editar). Os dados do período vêm uma vez, para todos."""
    if editor.audience == "client" or not editor.blocks:
        return Previews()
    state = await load_state(page, db, params)
    f = state.filters
    if f is None:
        message = state.error or page.t("relatorios.periodoInvalido")
        return Previews([message] * len(editor.blocks))
    # Só o formato das horas importa para formatar; os blocos podem ainda não valer.
    hours: Literal["hm", "decimal"] = "decimal" if editor.hours == "decimal" else "hm"
    config = ReportConfig.model_construct(hours=hours, blocks=editor.blocks)
    previews = Previews(
        label=page.t(
            "relatorios.editor.previa",
            de=format_day(page.locale, f.start),
            ate=format_day(page.locale, f.end),
        )
    )
    errors: dict[int, str] = {}
    for i, block in enumerate(editor.blocks):
        try:
            builder.check_block(block)
        except HTTPException as exc:
            errors[i] = page.api_message(exc)
    valid = [b for i, b in enumerate(editor.blocks) if i not in errors]
    found = iter(await scopes(page, db, state, valid, compare=False))
    for i, block in enumerate(editor.blocks):
        if i in errors:
            previews.blocks.append(errors[i])
        else:
            previews.blocks.append(block_view(page, state, config, block, i, next(found)))
    return previews


async def _editor_page(
    page: LoggedPage,
    db: DB,
    editor: EditorForm,
    *,
    model: ReportModel | None,
    hidden: list[tuple[str, str]],
    back: str,
    previews: Previews,
    status_code: int = 200,
) -> HTMLResponse:
    action = f"/relatorios/modelos/{model.public_id}" if model else "/relatorios/modelos"
    dimensions = {v: d for v in builder.VISUALS if (d := builder.dimensions_for(v))}
    # O filtro de cada bloco: as mesmas etiquetas da tela (nome do campo, rótulo, opções ou None
    # na busca de cliente, e os nomes), com os escolhidos de cada bloco.
    options = await service.choices(db, page.auth)
    labels = await service.client_labels(
        db, {c for b in editor.blocks if b.filters for c in b.filters.clients}
    )
    teams = [(str(t.id), t.name) for t in options.teams]
    people = [(str(p.id), p.name) for p in options.people]
    statuses = [(str(s.id), s.name) for s in options.statuses]
    clients = {NO_CLIENT: page.t("relatorios.semCliente")}
    clients.update({str(c): name for c, name in labels.items()})
    block_filters: list[tuple[str, list[tuple[str, str]] | None, dict[str, str]]] = []
    if teams:
        block_filters.append(("grupo", teams, dict(teams)))
    if len(people) > 1:
        block_filters.append(("pessoa", people, dict(people)))
    block_filters.append(("cliente", None, clients))
    block_filters.append(("status", statuses, dict(statuses)))
    chosen = [
        {
            "grupo": [str(t) for t in own.teams],
            "pessoa": [str(p) for p in own.people],
            "cliente": [NO_CLIENT] * own.no_client + [str(c) for c in own.clients],
            "status": [str(s) for s in own.statuses],
        }
        for own in (b.filters or FilterSpec() for b in editor.blocks)
    ]
    return page.render(
        "reports/editor.html",
        status_code=status_code,
        form=editor,
        model=model,
        action=action,
        hidden=hidden,
        back=back,
        dimensions=dimensions,
        categories=CATEGORIES,
        charts=CHARTS,
        topped=TOPPED,
        task_columns=[
            (c, page.t(f"relatorios.colunas.{TASK_COLUMN_KEYS[c]}")) for c in builder.TASK_COLUMNS
        ],
        default_columns=builder.DEFAULT_COLUMNS,
        measure_names={m: page.t(f"relatorios.medidas.{m}") for m in builder.MEASURES},
        visual_options=[(v, page.t(f"relatorios.visuais.{v}")) for v in builder.VISUALS],
        dimension_options={
            visual: [(d, page.t(f"relatorios.dimensoes.{d}").capitalize()) for d in options]
            for visual, options in dimensions.items()
        },
        # As medidas que cabem em cada bloco, com o agrupamento escolhido.
        measure_options=[
            [
                (m, page.t(f"relatorios.medidas.{m}"))
                for m in builder.measures_for(b.visual, b.dimension)
            ]
            for b in editor.blocks
        ],
        order_options=[(o, page.t(f"relatorios.ordens.{o}")) for o in ("desc", "asc", "name")],
        elapsed=builder.ELAPSED,
        # A medida da linha das barras + linha: as da mesma unidade da das barras.
        partner_options=[
            [
                (m, page.t(f"relatorios.medidas.{m}"))
                for m in builder.measures_for(b.visual, b.dimension)
                if m != b.measures[0] and builder.unit(m) == builder.unit(b.measures[0])
            ]
            if b.visual == "combo"
            else []
            for b in editor.blocks
        ],
        referenced=REFERENCED,
        reference_options=[
            (r, page.t(f"relatorios.editor.referencias.{r}")) for r in ("none", "mean", "median")
        ],
        aggregate_options=[
            (a, page.t(f"relatorios.editor.agregacoes.{a}")) for a in ("median", "mean")
        ],
        period_options=[("", page.t("relatorios.editor.periodoDaTela"))]
        + [(s, page.t(f"relatorios.periodos.{key}")) for s, key in RELATIVE_KEYS.items()],
        block_filters=block_filters,
        sized=SIZED,
        # O formato das horas e as casas de cada bloco: só onde valem.
        timed=[
            b.visual == "tasks" or bool(set(b.measures) & set(builder.DURATIONS))
            for b in editor.blocks
        ],
        fractional=[
            b.visual == "tasks"
            or bool(set(b.measures) & {*builder.DURATIONS, *builder.PERCENT, *builder.RATES})
            for b in editor.blocks
        ],
        hours_options=[
            ("", page.t("relatorios.editor.horasDoModelo")),
            ("hm", page.t("relatorios.editor.formatoHm")),
            ("decimal", page.t("relatorios.editor.formatoDecimal")),
        ],
        decimal_options=[("", page.t("relatorios.editor.casasPadrao"))]
        + [(str(d), page.t("relatorios.editor.casasN", n=d)) for d in (0, 1, 2)],
        colored=COLORED,
        color_options=[("", page.t("relatorios.editor.cores.chart-1"))]
        + [(c, page.t(f"relatorios.editor.cores.{c}")) for c in SERIES[1:]],
        width_options=[
            ("", page.t("relatorios.editor.larguras.auto")),
            ("half", page.t("relatorios.editor.larguras.half")),
            ("full", page.t("relatorios.editor.larguras.full")),
        ],
        height_options=[(h, page.t(f"relatorios.editor.alturas.{h}")) for h in ("s", "m", "l")],
        client_columns=[
            (c, page.t(f"relatorios.paraCliente.colunas.{CLIENT_COLUMN_KEYS[c]}"))
            for c in CLIENT_COLUMNS
        ],
        orientation_options=[
            (o, page.t(f"relatorios.editor.orientacoes.{o}")) for o in ("portrait", "landscape")
        ],
        chosen=chosen,
        placeholders=[
            block_title(page, b, b.dimension) or page.t("relatorios.editor.semTitulo")
            for b in editor.blocks
        ],
        previews=previews,
    )


def _base(page: LoggedPage, base: str | None, models: list[ReportModel]) -> EditorForm:
    """O formulário de um modelo novo: os blocos do modelo de onde ele saiu."""
    source = next((m for m in models if str(m.public_id) == base), None)
    if source is not None:
        config = saved.config_of(source)
        name = page.t("relatorios.editor.copiaDe", nome=source.name)[: saved.MAX_NAME]
    else:
        config = BUILTINS.get(base or "", BUILTINS["produtividade"])
        name = ""
    return EditorForm(
        name=name,
        description=config.description,
        hours=config.hours,
        audience=config.audience,
        show_people=config.show_people,
        client=config.client,
        pdf=config.pdf,
        blocks=list(config.blocks),
    )


@router.get("/relatorios/modelos/novo")
async def new_model(
    page: LoggedPageDep,
    db: DB,
    params: ParamsDep,
    base: str | None = None,
) -> HTMLResponse:
    """Salvar como modelo: os blocos do modelo aberto e os filtros da tela."""
    models = await saved.list_mine(db, page.auth)
    try:
        editor = _base(page, base, models)
    except HTTPException as exc:
        editor = EditorForm(blocks=[NEW_BLOCK], error=page.api_message(exc))
    return await _editor_page(
        page,
        db,
        editor,
        model=None,
        hidden=params.hidden(),
        back=with_query("/relatorios", {"aba": base}),
        previews=await _previews(page, db, editor, params),
    )


@router.get("/relatorios/modelos/{model_id}/editar")
async def edit_model(page: LoggedPageDep, db: DB, model_id: uuid.UUID) -> HTMLResponse:
    model = await saved.get(db, page.auth, model_id)
    back = with_query("/relatorios", {"aba": str(model_id)})
    try:
        config = saved.config_of(model)
    except HTTPException as exc:
        editor = EditorForm(name=model.name, blocks=[NEW_BLOCK], error=page.api_message(exc))
    else:
        editor = EditorForm(
            name=model.name,
            description=config.description,
            hours=config.hours,
            is_default=model.is_default,
            audience=config.audience,
            show_people=config.show_people,
            client=config.client,
            pdf=config.pdf,
            blocks=list(config.blocks),
        )
    previews = await _previews(page, db, editor, Params(aba=str(model_id)))
    return await _editor_page(
        page, db, editor, model=model, hidden=[], back=back, previews=previews
    )


@router.post("/relatorios/modelos")
async def create_model(page: LoggedPageDep, db: DB) -> Response:
    return await _submit(page, db, None)


@router.post("/relatorios/modelos/{model_id}")
async def update_model(page: LoggedPageDep, db: DB, model_id: uuid.UUID) -> Response:
    return await _submit(page, db, await saved.get(db, page.auth, model_id))


async def _submit(page: LoggedPage, db: DB, model: ReportModel | None) -> Response:
    """Salvar, ou só refazer o formulário (adicionar, remover, mover, trocar o visual)."""
    form = await page.request.form()
    check_csrf(page, str(form.get("csrf_token", "")))
    editor, action = _read_editor(form)
    hidden = form_params(form).hidden()
    back = with_query("/relatorios", {"aba": str(model.public_id) if model else None})
    # A prévia: o modelo novo com o período e os filtros da tela; o salvo, com os dele.
    params = form_params(form) if model is None else Params(aba=str(model.public_id))
    if action != "salvar":
        _apply(editor, action)
        previews = await _previews(page, db, editor, params)
        return await _editor_page(
            page, db, editor, model=model, hidden=hidden, back=back, previews=previews
        )

    for i, block in enumerate(editor.blocks):
        try:
            builder.check_block(block)
            if block.filters is not None:  # o filtro do bloco, contra o alcance da pessoa
                own = block.filters
                today = datetime.now(TIMEZONE).date()
                await service.resolve(
                    db,
                    page.auth,
                    start=today,
                    end=today,
                    teams=own.teams,
                    people=own.people,
                    clients=own.clients,
                    no_client=own.no_client,
                    statuses=own.statuses,
                )
        except HTTPException as exc:
            editor.errors[i] = page.api_message(exc)
    if not editor.blocks and editor.audience == "internal":
        editor.error = page.t("relatorios.editor.semBlocos")
    if editor.errors or editor.error:
        previews = await _previews(page, db, editor, params)
        return await _editor_page(
            page,
            db,
            editor,
            model=model,
            hidden=hidden,
            back=back,
            previews=previews,
            status_code=422,
        )

    try:
        if model is None:
            # O período e os filtros vêm da tela de onde o modelo saiu.
            state = await load_state(page, db, form_params(form))
            period, filters = state.specs() if state.start and state.end else (None, None)
            config = ReportConfig(
                period=period or PeriodSpec(),
                filters=filters or FilterSpec(),
                description=editor.description,
                hours=editor.hours,
                audience=editor.audience,
                show_people=editor.show_people,
                client=editor.client,
                pdf=editor.pdf,
                blocks=editor.blocks,
            )
        else:
            config = ReportConfig.model_validate(
                {
                    **saved.config_of(model).model_dump(),
                    "description": editor.description,
                    "hours": editor.hours,
                    "audience": editor.audience,
                    "show_people": editor.show_people,
                    "client": editor.client,
                    "pdf": editor.pdf,
                    "blocks": editor.blocks,
                }
            )
        model = await saved.save(
            db, page.auth, model, name=editor.name, config=config, is_default=editor.is_default
        )
    except HTTPException as exc:
        editor.error = page.api_message(exc)
        previews = await _previews(page, db, editor, params)
        return await _editor_page(
            page,
            db,
            editor,
            model=model,
            hidden=hidden,
            back=back,
            previews=previews,
            status_code=422,
        )
    await db.commit()
    response = RedirectResponse(with_query("/relatorios", {"aba": str(model.public_id)}), 303)
    page.flash(response, ("success", page.t("relatorios.editor.salvo")))
    return response


@router.post("/relatorios/modelos/{model_id}/excluir")
async def delete_model(page: LoggedPageDep, db: DB, model_id: uuid.UUID) -> Response:
    form = await page.request.form()
    check_csrf(page, str(form.get("csrf_token", "")))
    model = await saved.get(db, page.auth, model_id)
    await saved.delete(db, model)
    await db.commit()
    response = RedirectResponse("/relatorios", status_code=303)
    page.flash(response, ("success", page.t("relatorios.editor.excluido")))
    return response
