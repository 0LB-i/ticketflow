"""Relatórios: o editor de um modelo pessoal (docs/14 §14.8.1 e §14.8.3) e o "Salvar filtros".

O formulário tem os campos de cada bloco (`b<i>-visual`, `b<i>-agrupar`, `b<i>-medida(s)`…), lidos
de `request.form()`. Adicionar, remover, mover e mudar as escolhas de um bloco refazem o
formulário pelo HTMX, sem salvar; só `acao=salvar` grava. O modelo novo leva o período e os
filtros da tela, em campos escondidos. Cada bloco mostra a prévia, calculada como na tela.
"""

import uuid
from dataclasses import dataclass, field, replace
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
    REFERENCED,
    Block,
    FilterSpec,
    PeriodSpec,
    ReportConfig,
)
from chamados.modules.reports.models import ReportModel
from chamados.web.formatting import format_day
from chamados.web.page import LoggedPage, LoggedPageDep, check_csrf
from chamados.web.reports_blocks import block_title, block_view
from chamados.web.reports_state import Params, ParamsDep, form_params, load_state, with_query

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


NEW_BLOCK = Block(visual="table", dimension="person", measures=["hours"])


@dataclass
class EditorForm:
    name: str = ""
    hours: str = "hm"
    is_default: bool = False
    audience: str = "internal"  # ou "client": o relatório para o cliente (§14.8.5)
    show_people: bool = False
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
    measures = [m for m in offered if m in checked]
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
    return Block(
        visual=visual,
        title=one("titulo")[:120],
        dimension=dimension,
        measures=measures,
        top=min(int(top), 100) if top.isdigit() and int(top) > 0 else None,
        order=order if order in ("desc", "asc", "name") else "desc",
        only_overtime=one("extras") == "1",
        # A média só nos tempos até a conclusão: sem eles, volta à mediana.
        aggregate="mean"
        if one("agregacao") == "mean" and set(measures) & set(builder.ELAPSED)
        else "median",
        area=visual == "line" and one("area") == "1",
        reference=next(
            (r for r in ("mean", "median") if r == one("referencia") and visual in REFERENCED),
            "none",
        ),
    )


def _read_editor(form: FormData) -> tuple[EditorForm, str]:
    count = form.get("blocos")
    total = min(int(count), 12) if isinstance(count, str) and count.isdigit() else 0
    hours = form.get("horas")
    editor = EditorForm(
        name=str(form.get("nome", "")),
        hours=hours if hours in ("hm", "decimal") else "hm",
        is_default=form.get("inicial") == "1",
        audience="client" if form.get("publico") == "client" else "internal",
        show_people=form.get("atendeu") == "1",
        blocks=[_read_block(form, i) for i in range(total)],
    )
    return editor, str(form.get("acao", "salvar"))


def _apply(editor: EditorForm, action: str) -> None:
    """Adicionar, remover e mover blocos (o formulário volta sem salvar)."""
    blocks = editor.blocks
    if action == "adicionar" and len(blocks) < 12:
        blocks.append(NEW_BLOCK.model_copy())
        return
    verb, _, number = action.partition("-")
    if not number.isdigit() or int(number) >= len(blocks):
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
    data = await service.facts(db, page.auth, f, builder.needs(editor.blocks), state.lookups)
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
    for i, block in enumerate(editor.blocks):
        try:
            builder.check_block(block)
        except HTTPException as exc:
            previews.blocks.append(page.api_message(exc))
        else:
            previews.blocks.append(block_view(page, state, f, config, data, block, i))
    return previews


def _editor_page(
    page: LoggedPage,
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
        hours=config.hours,
        audience=config.audience,
        show_people=config.show_people,
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
    return _editor_page(
        page,
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
            hours=config.hours,
            is_default=model.is_default,
            audience=config.audience,
            show_people=config.show_people,
            blocks=list(config.blocks),
        )
    previews = await _previews(page, db, editor, Params(aba=str(model_id)))
    return _editor_page(page, editor, model=model, hidden=[], back=back, previews=previews)


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
        return _editor_page(page, editor, model=model, hidden=hidden, back=back, previews=previews)

    for i, block in enumerate(editor.blocks):
        try:
            builder.check_block(block)
        except HTTPException as exc:
            editor.errors[i] = page.api_message(exc)
    if not editor.blocks and editor.audience == "internal":
        editor.error = page.t("relatorios.editor.semBlocos")
    if editor.errors or editor.error:
        previews = await _previews(page, db, editor, params)
        return _editor_page(
            page, editor, model=model, hidden=hidden, back=back, previews=previews, status_code=422
        )

    try:
        if model is None:
            # O período e os filtros vêm da tela de onde o modelo saiu.
            state = await load_state(page, db, form_params(form))
            period, filters = state.specs() if state.start and state.end else (None, None)
            config = ReportConfig(
                period=period or PeriodSpec(),
                filters=filters or FilterSpec(),
                hours=editor.hours,
                audience=editor.audience,
                show_people=editor.show_people,
                blocks=editor.blocks,
            )
        else:
            config = ReportConfig.model_validate(
                {
                    **saved.config_of(model).model_dump(),
                    "hours": editor.hours,
                    "audience": editor.audience,
                    "show_people": editor.show_people,
                    "blocks": editor.blocks,
                }
            )
        model = await saved.save(
            db, page.auth, model, name=editor.name, config=config, is_default=editor.is_default
        )
    except HTTPException as exc:
        editor.error = page.api_message(exc)
        previews = await _previews(page, db, editor, params)
        return _editor_page(
            page, editor, model=model, hidden=hidden, back=back, previews=previews, status_code=422
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
