"""Relatórios: a aba Clientes geral (docs/14 §14.7). Só o período e o status (que abre com os
concluídos, como a aba Clientes); ao gerar, o relatório detalhado de cada cliente com horas no
período, um depois do outro: os cartões da aba Clientes e as tarefas, com o PDF detalhado dele
(o mesmo da aba Clientes com um cliente só, que vai para o Histórico). Sem os gráficos e sem
"Sem cliente".
"""

from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from chamados.db.session import DB
from chamados.modules.reports import builder, service
from chamados.modules.reports.builder import BUILTINS, Block
from chamados.web.formatting import format_date
from chamados.web.page import LoggedPage, LoggedPageDep
from chamados.web.reports import period_view, tab
from chamados.web.reports_blocks import formatter
from chamados.web.reports_state import TABS, Params, State, Values, load_state, with_query

router = APIRouter()

PATH = "/relatorios/clientes-geral"

# Os cartões da aba Clientes (horas, no plano, excedentes, tarefas, registrados, concluídos), por
# cliente.
BY_CLIENT = Block(
    visual="table", dimension="client", measures=BUILTINS["clientes"].blocks[0].measures
)


async def _clients(
    page: LoggedPage, db: DB, state: State, f: service.Filters
) -> list[dict[str, Any]]:
    """Cada cliente com horas no período, pelo nome: os cartões, as tarefas (o dia, o chamado, as
    horas no plano, as excedentes e o tempo) com o total e o link do PDF detalhado."""
    want = builder.needs([BY_CLIENT])
    want.rows.add("tasks")
    data = await service.facts(db, page.auth, f, want, state.lookups)
    result = builder.run(data, BY_CLIENT, f.start, f.end)
    hours = formatter(page, "hours")
    by_client: dict[int | None, list[service.TaskFact]] = {}
    for t in data.tasks:
        by_client.setdefault(t.client_id, []).append(t)

    def times(minutes: int, excess: int) -> list[str]:
        return [hours(minutes - excess), hours(excess), hours(minutes)]

    clients = []
    for row in sorted(result.rows, key=lambda r: (r.label or "").casefold()):
        if not isinstance(row.key, int) or not row.values["hours"]:
            continue  # "Sem cliente" e os sem horas
        tasks = by_client.get(row.key, [])
        public_id = str(data.clients[row.key].public_id)
        clients.append(
            {
                "name": row.label,
                "cards": [
                    (page.t(f"relatorios.medidas.{m}"), formatter(page, m)(row.values[m]))
                    for m in BY_CLIENT.measures
                ],
                "tasks": [
                    (
                        format_date(page.locale, t.done_at),
                        t.ticket_number,
                        t.ticket_title,
                        times(t.minutes, t.excess),
                    )
                    for t in tasks
                ],
                # A linha do total (reports/_blocks.html, `table`): da coluna do chamado em diante.
                "total": [
                    ("", None),
                    *(
                        (text, None)
                        for text in times(
                            sum(t.minutes for t in tasks), sum(t.excess for t in tasks)
                        )
                    ),
                ],
                "pdf": with_query(
                    "/relatorios/pdf",
                    {**state.query, "aba": "clientes", "cliente": [public_id], "detalhado": "1"},
                ),
            }
        )
    return clients


@router.get(PATH)
async def all_clients_page(
    page: LoggedPageDep,
    db: DB,
    periodo: str | None = None,
    de: str | None = None,
    ate: str | None = None,
    dias: str | None = None,
    status: Values = None,
    gerar: bool = False,
) -> HTMLResponse:
    """A aba com o período e o status; com `gerar`, os relatórios dos clientes embaixo."""
    # Os filtros da aba Clientes (o status começa nos concluídos), sem grupo, pessoa e cliente.
    params = Params(aba="clientes", periodo=periodo, de=de, ate=ate, dias=dias, status=status)
    state = await load_state(page, db, params)
    query = {k: state.query[k] for k in ("periodo", "de", "ate", "dias", "status")}
    status_options = [(str(s.id), s.name) for s in state.options.statuses]
    clients = None
    if gerar and state.filters is not None:
        clients = await _clients(page, db, state, state.filters)
    return page.render(
        "reports/all_clients.html",
        tabs=[tab(page, s, with_query("/relatorios", {"aba": s})) for s in TABS],
        period=period_view(page, state, PATH, query),
        status_options=status_options,
        status_names=dict(status_options),
        query_status=query["status"],
        error=state.error,
        clients=clients,
        columns=[
            page.t("relatorios.colunas.quando"),
            page.t("relatorios.colunas.chamado"),
            *(page.t(f"relatorios.medidas.{m}") for m in ("in_plan", "excess")),
            page.t("relatorios.colunas.tempo"),
        ],
    )
