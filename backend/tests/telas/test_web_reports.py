"""Tela dos relatórios no servidor (ADR 0011, docs/14 §14.7 e §14.8).

Cenário (a fixture `cenario`): Ana e Bia (supervisora) no TI, Caio na Infra. O escopo é decidido
pela API (`reports/service.resolve`); a tela repassa os filtros e mostra o erro.
"""

import csv
import io
import re
import uuid
from datetime import date, datetime, time, timedelta
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from chamados.modules.audit.models import AuditLog
from chamados.modules.catalog.models import TicketStatus
from chamados.modules.clients.models import Client
from chamados.modules.organization.models import Team
from chamados.modules.reports import model_pdf
from chamados.modules.reports.builder import relative_period, year_before
from chamados.modules.reports.models import ReportModel
from chamados.modules.system.models import SystemSetting, WorkSchedule
from chamados.modules.tickets.models import Ticket
from chamados.web.formatting import TIMEZONE, format_day, format_month
from chamados.web.reports_blocks import wide
from chamados.web.reports_state import parse_minutes
from tests.apoio import API, dia_util_passado, em, formulario, registrar, status_id, tarefa
from tests.conftest import criar_cliente, criar_usuario, entrar, outra_sessao


def _um_dia(dia: date, **extra: str | list[str]) -> dict[str, str | list[str]]:
    return {"periodo": "personalizado", "de": dia.isoformat(), "ate": dia.isoformat(), **extra}


def _pdf(html: str, arquivo: str = "csv") -> dict[str, list[str]]:
    """Os parâmetros de um link da API no menu Baixar (o primeiro CSV; o PDF é o do modelo, da
    tela, e os CSV levam os mesmos filtros)."""
    achado = re.search(rf'<a href="(/api/v1/reports/{arquivo}\?[^"]+)" download', html)
    assert achado, f"sem o link do {arquivo}"
    return parse_qs(urlsplit(achado.group(1).replace("&amp;", "&")).query)


def test_relatorio_do_mes(client: TestClient, cenario: dict[str, Any]) -> None:
    r = client.get("/relatorios/blocos")
    assert r.status_code == 200
    assert "<title>Relatórios · TicketFlow</title>" in r.text
    hoje = datetime.now(TIMEZONE).date()
    mes = format_month("pt-BR", hoje)
    # O padrão é o mês atual, que anda com o calendário; os meses da lista ficam num grupo.
    assert '<optgroup label="Relativos">' in r.text and '<optgroup label="Meses">' in r.text
    assert '<option value="mes-atual" selected>Mês atual</option>' in r.text
    assert f'<option value="{hoje:%Y-%m}">{mes}</option>' in r.text
    assert '<option value="personalizado">Personalizado</option>' in r.text
    inicio, fim = relative_period("mes-atual", hoje)
    assert f"De {format_day('pt-BR', inicio)} a {format_day('pt-BR', fim)}" in r.text
    # Na impressão, no lugar das abas e dos filtros: o modelo e o período.
    periodo = f"De {format_day('pt-BR', inicio)} a {format_day('pt-BR', fim)}"
    assert (
        f'<p class="hidden w-full text-muted print:block">Produtividade · {periodo}</p>' in r.text
    )
    assert "Chamados registrados" in r.text
    assert 'aria-current="page">Produtividade</a>' in r.text
    pdf = _pdf(r.text)
    assert pdf["start"] == [hoje.replace(day=1).isoformat()]
    assert pdf["locale"] == ["pt-BR"]
    # O menu Baixar: o PDF do modelo, o CSV da tabela da aba e o de todas as tarefas, com os
    # mesmos filtros.
    assert "/relatorios/pdf?periodo=mes-atual&amp;aba=produtividade" in r.text
    assert _pdf(r.text, "csv")["table"] == ["people"]
    assert "CSV de todas as tarefas" in r.text and "table=tasks" in r.text
    # A Ana só vê o próprio trabalho: não escolhe grupo nem pessoa. Cliente e status, sim.
    assert "Todos os grupos" not in r.text
    assert "Todas as pessoas" not in r.text
    assert '<label for="campo-cliente" class="font-medium">Cliente</label>' in r.text
    # O cliente é uma busca (são milhares): "Sem cliente" vem nas opções dela.
    assert 'placeholder="Todos os clientes" hx-get="/relatorios/clientes"' in r.text
    assert '<option value="">Todos os status</option>' in r.text

    client.cookies.clear()  # sem sessão, vai para o login e volta depois
    r = client.get("/relatorios", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login?volta=%2Frelatorios"


def test_numeros_graficos_e_abas(client: TestClient, cenario: dict[str, Any], db: Session) -> None:
    dia = dia_util_passado()
    padaria = criar_cliente(db, "Padaria Pão Quente", "11222333000181")
    numero = registrar(client, cenario, client_id=padaria, title="Servidor parado")["number"]
    tarefa(client, numero, 90, em(dia, 19))  # 60 min fora do expediente
    tarefa(client, numero, 45, em(dia, 10))

    r = client.get("/relatorios/blocos", params=_um_dia(dia))
    assert '<dd class="mt-1 text-2xl font-semibold">2h15</dd>' in r.text
    assert '<dd class="mt-1 text-2xl font-semibold">1h</dd>' in r.text
    # Colunas por dia (com a dica da data e do valor) e barras por pessoa.
    assert f'aria-label="{format_day("pt-BR", dia)}: 2h15"' in r.text
    assert 'height="100.00%"' not in r.text  # o topo do eixo fica acima do maior valor
    assert '<svg width="85.00%" height="16"' in r.text
    # A linha da pessoa aplica o filtro dela ao ser clicada (detalhar).
    achado = re.search(
        r'<td class="px-3 py-2"><a href="([^"]+)" hx-boost="true" class="hover:underline">Ana</a>',
        r.text,
    )
    assert achado and f"pessoa={cenario['ana']}" in achado.group(1)

    filtros = _um_dia(dia)
    r = client.get("/relatorios/blocos", params={**filtros, "aba": "clientes"})
    assert 'aria-current="page">Clientes</a>' in r.text
    assert _pdf(r.text, "csv")["table"] == ["clients"]
    assert "Horas por cliente (os 10 maiores)" in r.text
    assert 'class="hover:underline">Padaria Pão Quente</a></td>' in r.text
    assert f"cliente={padaria}" in r.text
    # As abas levam os filtros junto.
    assert f"de={dia.isoformat()}" in r.text

    r = client.get("/relatorios/blocos", params={**filtros, "aba": "horas-extras"})
    assert "Hora extra é o tempo de tarefa" not in r.text  # o expediente usado, só no PDF
    assert f'<a href="/chamados/{numero}" class="text-primary underline tabular-nums">' in r.text
    assert "Tarefas fora do expediente" in r.text


def test_supervisor_escolhe_pessoa(
    client: TestClient,
    cenario: dict[str, Any],
    db: Session,
) -> None:
    dia = dia_util_passado()
    numero = registrar(client, cenario)["number"]
    tarefa(client, numero, 30, em(dia, 10))

    # A Ana não escolhe pessoa, e forçar a da Bia mostra o erro da API, sem o PDF.
    r = client.get("/relatorios/blocos", params=_um_dia(dia, pessoa=cenario["bia"]))
    assert "Você só pode ver os seus próprios números." in r.text
    assert '<button type="button" disabled' in r.text

    entrar(client, "bia@x.com")
    r = client.get("/relatorios/blocos", params=_um_dia(dia))
    assert '<option value="">Todas as pessoas</option>' in r.text
    assert f'<option value="{cenario["ana"]}">Ana</option>' in r.text
    assert "Todos os grupos" in r.text  # supervisiona o TI
    r = client.get(
        "/relatorios/blocos", params=_um_dia(dia, pessoa=cenario["ana"], grupo=cenario["ti"])
    )
    # A escolhida vira etiqueta e sai da lista; a lista passa a acrescentar.
    assert f'<input type="hidden" name="pessoa" value="{cenario["ana"]}">' in r.text
    assert f'<option value="{cenario["ana"]}" hidden disabled>Ana</option>' in r.text
    assert '<option value="">Adicionar…</option>' in r.text
    assert '<dd class="mt-1 text-2xl font-semibold">30min</dd>' in r.text
    pdf = _pdf(r.text)
    assert pdf["person"] == [cenario["ana"]] and pdf["team"] == [cenario["ti"]]
    # O link leva ao PDF do modelo, com os mesmos filtros.
    resposta = client.get(_link_pdf(r.text))
    assert resposta.status_code == 200
    assert resposta.content.startswith(b"%PDF")

    # Várias pessoas de uma vez.
    r = client.get(
        "/relatorios/blocos", params=_um_dia(dia, pessoa=[cenario["ana"], cenario["bia"]])
    )
    assert '<dd class="mt-1 text-2xl font-semibold">30min</dd>' in r.text
    assert _pdf(r.text)["person"] == [cenario["ana"], cenario["bia"]]


def test_filtro_de_cliente(client: TestClient, cenario: dict[str, Any], db: Session) -> None:
    padaria = criar_cliente(db, "Padaria Pão Quente", "11222333000181")
    # Vários clientes e "Sem cliente"; um valor que não é cliente fica de fora.
    r = client.get("/relatorios/blocos", params={"cliente": [padaria, "sem-cliente", "xyz"]})
    assert f'<input type="hidden" name="cliente" value="{padaria}">' in r.text
    assert "<span data-rotulo>Padaria Pão Quente</span>" in r.text
    assert '<input type="hidden" name="cliente" value="sem-cliente">' in r.text
    assert "<span data-rotulo>Sem cliente</span>" in r.text
    assert 'value="xyz"' not in r.text and "cliente=xyz&amp;" not in r.text
    pdf = _pdf(r.text)
    assert pdf["client"] == [padaria] and pdf["no_client"] == ["true"]
    # As abas levam os filtros junto.
    assert f"cliente=sem-cliente&amp;cliente={padaria}" in r.text


def test_busca_de_cliente_no_filtro(
    client: TestClient, cenario: dict[str, Any], db: Session
) -> None:
    """Os clientes não vêm na página: a busca traz "Sem cliente" e os que batem, inclusive os
    desativados (o relatório olha o passado), sem os já escolhidos."""
    padaria = criar_cliente(db, "Padaria Pão Quente", "11222333000181")
    antiga = criar_cliente(db, "Padaria Antiga", "11444777000161", ativo=False)
    r = client.get("/relatorios/blocos")
    assert "Padaria Pão Quente" not in r.text and "Cliente Padrão" not in r.text

    r = client.get("/relatorios/clientes")
    assert 'data-id="sem-cliente" data-nome="Sem cliente"' in r.text
    assert f'data-id="{padaria}"' in r.text and f'data-id="{cenario["cliente"]}"' in r.text
    r = client.get("/relatorios/clientes", params={"q": "padaria"})
    assert "Sem cliente" not in r.text and "Cliente Padrão" not in r.text
    assert f'data-id="{padaria}"' in r.text and f'data-id="{antiga}"' in r.text
    r = client.get("/relatorios/clientes", params={"q": "sem cli"})
    assert 'data-id="sem-cliente"' in r.text
    # Os escolhidos (as etiquetas, pelo hx-include) ficam de fora.
    r = client.get("/relatorios/clientes", params={"q": "", "cliente": [padaria, "sem-cliente"]})
    assert f'data-id="{padaria}"' not in r.text and "sem-cliente" not in r.text
    assert f'data-id="{antiga}"' in r.text
    r = client.get("/relatorios/clientes", params={"q": "xyz"})
    assert "Nenhum cliente encontrado" in r.text

    # O escolhido aparece com o nome, na etiqueta e no resumo.
    r = client.get("/relatorios/blocos", params={"cliente": antiga})
    assert "<span data-rotulo>Padaria Antiga</span>" in r.text
    assert 'aria-label="Tirar Padaria Antiga"' in r.text


def test_periodo_personalizado(client: TestClient, cenario: dict[str, Any]) -> None:
    # Ao escolher "Personalizado", as datas começam no primeiro dia do mês e em hoje.
    hoje = datetime.now(TIMEZONE).date()
    r = client.get("/relatorios/blocos", params={"periodo": "personalizado"})
    assert (
        f'id="campo-de" name="de" type="date" value="{hoje.replace(day=1).isoformat()}"' in r.text
    )
    assert f'id="campo-ate" name="ate" type="date" value="{hoje.isoformat()}"' in r.text
    assert _pdf(r.text)["end"] == [hoje.isoformat()]
    # As datas não aplicam ao mudar: o botão Aplicar envia.
    assert '<button type="submit"' in r.text and ">Aplicar</button>" in r.text
    assert ">Aplicar</button>" not in client.get("/relatorios/blocos").text

    r = client.get(
        "/relatorios/blocos",
        params={"periodo": "personalizado", "de": "2026-10-10", "ate": "2026-10-01"},
    )
    assert "A data final precisa ser igual ou depois da inicial." in r.text
    assert "Chamados registrados" not in r.text
    assert '<button type="button" disabled' in r.text
    r = client.get(
        "/relatorios/blocos", params={"periodo": "personalizado", "de": "", "ate": "2026-10-01"}
    )
    assert "A data final precisa ser igual ou depois da inicial." in r.text

    # Mais de 366 dias: o erro vem da API.
    r = client.get(
        "/relatorios/blocos",
        params={"periodo": "personalizado", "de": "2024-01-01", "ate": "2026-01-01"},
    )
    assert "O período pode ter no máximo 366 dias." in r.text

    # Período e aba desconhecidos: o mês atual, na primeira aba.
    r = client.get("/relatorios/blocos", params={"periodo": "1999-01", "aba": "xyz"})
    assert '<option value="mes-atual" selected>' in r.text
    assert 'aria-current="page">Produtividade</a>' in r.text


def test_formatos_do_relatorio() -> None:
    assert format_month("pt-BR", date(2026, 3, 1)) == "março de 2026"
    assert format_month("en", date(2026, 3, 1)) == "March 2026"
    assert format_day("pt-BR", date(2026, 10, 5)) == "05/10"
    assert format_day("en", date(2026, 10, 5)) == "10/05"


def test_periodos_relativos(client: TestClient, cenario: dict[str, Any]) -> None:
    # O cálculo está em tests/unidade/test_relatorios_construtor.py. Na tela: o período
    # escolhido, o intervalo e os downloads com as datas de hoje.
    agora = datetime.now(TIMEZONE).date()
    r = client.get("/relatorios/blocos", params={"periodo": "ultimos-7-dias", "aba": "clientes"})
    assert '<option value="ultimos-7-dias" selected>Últimos 7 dias</option>' in r.text
    inicio = agora - timedelta(days=6)
    assert f"De {format_day('pt-BR', inicio)} a {format_day('pt-BR', agora)}" in r.text
    assert _pdf(r.text, "csv")["start"] == [inicio.isoformat()]
    # As abas mantêm o período relativo (não as datas): o link continua valendo amanhã.
    (aba,) = _links(r.text, "Produtividade")
    assert "periodo=ultimos-7-dias" in aba and "de=" not in aba


def test_ultimos_n_dias(client: TestClient, cenario: dict[str, Any]) -> None:
    agora = datetime.now(TIMEZONE).date()
    # O campo dos dias só aparece nesse período.
    r = client.get("/relatorios", params={"periodo": "mes-atual"})
    assert 'name="dias"' not in r.text
    r = client.get("/relatorios/blocos", params={"periodo": "ultimos-n-dias", "dias": "45"})
    assert '<option value="ultimos-n-dias" selected>Últimos N dias</option>' in r.text
    assert 'name="dias" type="number" value="45"' in r.text
    inicio = agora - timedelta(days=44)
    assert f"De {format_day('pt-BR', inicio)} a {format_day('pt-BR', agora)}" in r.text
    assert _pdf(r.text, "csv")["start"] == [inicio.isoformat()]
    (aba,) = _links(r.text, "Produtividade")
    assert "periodo=ultimos-n-dias" in aba and "dias=45" in aba
    # Fora de 1 a 366 (ou sem número), o padrão: 30.
    for dias in ("0", "367", "x", "", "²", "9" * 5000):
        r = client.get("/relatorios/blocos", params={"periodo": "ultimos-n-dias", "dias": dias})
        assert 'name="dias" type="number" value="30"' in r.text
    # O modelo guarda os N e os usa ao abrir.
    modelo = _criar(client, "Quinzena", periodo="ultimos-n-dias", dias="15")
    r = client.get("/relatorios/blocos", params={"aba": modelo})
    assert 'name="dias" type="number" value="15"' in r.text
    # O detalhar a partir dele volta aos mesmos N dias.
    html = client.get(
        "/relatorios/blocos",
        params=_um_dia(agora, origem="ultimos-n-dias:15"),
    ).text
    (voltar,) = _links(html, "Voltar para Últimos 15 dias")
    assert "periodo=ultimos-n-dias" in voltar and "dias=15" in voltar
    html = client.get("/relatorios/blocos", params=_um_dia(agora, origem="ultimos-n-dias:1")).text
    assert _links(html, "Voltar para Último dia")
    html = client.get("/relatorios/blocos", params=_um_dia(agora, origem="ultimos-n-dias:²")).text
    assert "Voltar para" not in html


# --- modelos (docs/14 §14.8) -----------------------------------------------------------------

TABELA = {"b0-visual": "table", "b0-agrupar": "person", "b0-medidas": ["hours", "tasks"]}


def _criar(client: TestClient, nome: str = "Mensal", **campos: Any) -> str:
    """Cria um modelo pelo editor e devolve o id (o da aba para onde a tela volta)."""
    dados = formulario(client, nome=nome, horas="hm", blocos="1", acao="salvar", **TABELA)
    r = client.post("/relatorios/modelos", data={**dados, **campos}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return parse_qs(urlsplit(r.headers["location"]).query)["aba"][0]


def _blocos(html: str) -> list[str]:
    """O visual escolhido em cada bloco do editor."""
    return re.findall(
        r'name="b\d+-visual"[^>]*>(?:\s*<option[^>]*>[^<]*</option>)*?\s*'
        r'<option value="(\w+)" selected',
        html,
    )


def test_salvar_como_modelo_e_os_filtros_salvos(
    client: TestClient, cenario: dict[str, Any]
) -> None:
    # Da aba Clientes, com os filtros da tela: o editor traz os blocos dela.
    r = client.get(
        "/relatorios/modelos/novo",
        params={"base": "clientes", "periodo": "ultimos-7-dias", "cliente": "sem-cliente"},
    )
    assert r.status_code == 200
    assert "<title>Novo modelo · TicketFlow</title>" in r.text
    assert '<input type="hidden" name="blocos" value="3">' in r.text
    assert _blocos(r.text) == ["cards", "bars", "table"]
    assert '<input type="hidden" name="periodo" value="ultimos-7-dias">' in r.text
    assert '<input type="hidden" name="cliente" value="sem-cliente">' in r.text

    modelo = _criar(client, "Sem cliente", periodo="ultimos-7-dias", cliente="sem-cliente")
    r = client.get("/relatorios/blocos", params={"aba": modelo})
    assert "Modelo salvo." in r.text
    assert 'aria-current="page">Sem cliente</a>' in r.text
    # Sem filtro na URL, valem os do modelo.
    assert '<option value="ultimos-7-dias" selected>Últimos 7 dias</option>' in r.text
    assert '<input type="hidden" name="cliente" value="sem-cliente">' in r.text
    assert f'href="/relatorios/modelos/{modelo}/editar"' in r.text
    assert "Salvar filtros" not in r.text
    # Modelo da pessoa: sem o PDF e o CSV da aba (fase 4), com o CSV de todas as tarefas.
    assert "/api/v1/reports/pdf" not in r.text and "table=tasks" in r.text
    # Nas outras abas, o modelo abre com os filtros dele.
    assert f'href="/relatorios?aba={modelo}"' in client.get("/relatorios/blocos").text

    # Mexer num filtro mostra "Salvar filtros", que os guarda no modelo.
    r = client.get("/relatorios/blocos", params={"aba": modelo, "periodo": "mes-anterior"})
    assert "Salvar filtros" in r.text
    r = client.post(
        f"/relatorios/modelos/{modelo}/filtros",
        data=formulario(client, periodo="mes-anterior"),
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"] == f"/relatorios?aba={modelo}"
    r = client.get("/relatorios/blocos", params={"aba": modelo})
    assert "Filtros salvos no modelo." in r.text
    assert '<option value="mes-anterior" selected>Mês anterior</option>' in r.text
    assert 'name="cliente" value="sem-cliente"' not in r.text
    assert "Salvar filtros" not in r.text


def test_editor_monta_os_blocos(client: TestClient, cenario: dict[str, Any]) -> None:
    def refazer(acao: str, **campos: Any) -> str:
        dados = formulario(client, nome="Novo", horas="hm", acao=acao, **campos)
        r = client.post("/relatorios/modelos", data=dados)
        assert r.status_code == 200, r.text
        return r.text

    html = refazer("adicionar", blocos="1", **{"b0-visual": "cards", "b0-medidas": "hours"})
    assert '<input type="hidden" name="blocos" value="2">' in html
    assert _blocos(html) == ["cards", "table"]
    # Subir o segundo bloco.
    dois = {
        "blocos": "2",
        "b0-visual": "cards",
        "b0-medidas": "hours",
        **{k.replace("b0", "b1"): v for k, v in TABELA.items()},
    }
    assert _blocos(refazer("subir-1", **dois)) == ["table", "cards"]
    assert _blocos(refazer("remover-0", **dois)) == ["table"]
    # Trocar o visual ajusta o resto: a linha só agrupa por período e mostra uma medida.
    html = refazer("atualizar", blocos="1", **{**TABELA, "b0-visual": "line"})
    assert '<option value="day" selected>Dia</option>' in html
    assert '<option value="person"' not in html
    assert 'name="b0-medida"' in html and 'name="b0-medidas"' not in html
    assert 'hx-select="#editor"' in html

    def salvar(**campos: Any) -> str:
        dados = formulario(client, **{"horas": "hm", "blocos": "1", "acao": "salvar", **campos})
        r = client.post("/relatorios/modelos", data=dados)
        assert r.status_code == 422, r.text
        return r.text

    assert "Informe o nome do modelo." in salvar(nome=" ", **TABELA)
    sem_medida = {"b0-visual": "table", "b0-agrupar": "client"}
    assert "Escolha ao menos uma medida." in salvar(nome="X", **sem_medida)
    assert "Adicione ao menos um bloco." in salvar(nome="X", blocos="0")
    _criar(client, "Mensal")
    assert "Você já tem um modelo com este nome." in salvar(nome="MENSAL", **TABELA)


def test_modelo_inicial_e_o_de_outra_pessoa(
    client: TestClient, cenario: dict[str, Any], db: Session
) -> None:
    primeiro = _criar(client, "Primeiro", inicial="1")
    assert 'aria-current="page">Primeiro</a>' in client.get("/relatorios/blocos").text
    segundo = _criar(client, "Segundo", inicial="1")
    assert 'aria-current="page">Segundo</a>' in client.get("/relatorios/blocos").text
    iniciais = db.scalars(select(ReportModel.name).where(ReportModel.is_default)).all()
    assert iniciais == ["Segundo"]

    # A Bia não vê nem mexe nos modelos da Ana.
    entrar(client, "bia@x.com")
    r = client.get("/relatorios/blocos", params={"aba": primeiro})
    assert "Primeiro" not in r.text and 'aria-current="page">Produtividade</a>' in r.text
    assert client.get(f"/relatorios/modelos/{primeiro}/editar").status_code == 404
    r = client.post(f"/relatorios/modelos/{primeiro}/excluir", data=formulario(client))
    assert r.status_code == 404

    entrar(client, "ana@x.com")
    r = client.get(f"/relatorios/modelos/{segundo}/editar")
    assert "<title>Editar modelo · TicketFlow</title>" in r.text
    assert 'name="inicial" value="1" checked' in r.text
    r = client.post(
        f"/relatorios/modelos/{segundo}/excluir", data=formulario(client), follow_redirects=False
    )
    assert r.status_code == 303
    r = client.get("/relatorios/blocos")
    assert "Modelo excluído." in r.text and "Segundo" not in r.text
    assert 'aria-current="page">Produtividade</a>' in r.text


def test_csv_de_um_bloco(client: TestClient, cenario: dict[str, Any], db: Session) -> None:
    dia = dia_util_passado()
    numero = registrar(client, cenario, title="Servidor parado")["number"]
    tarefa(client, numero, 90, em(dia, 19))  # 60 min fora do expediente
    tarefa(client, numero, 30, em(dia, 10))
    filtros = _um_dia(dia, aba="horas-extras")
    r = client.get("/relatorios/blocos", params=filtros)
    assert "/relatorios/csv?" in r.text and "bloco=3" in r.text

    r = client.get("/relatorios/csv", params={**filtros, "bloco": "3"})
    assert r.status_code == 200
    assert "relatorio-bloco-4-" in r.headers["content-disposition"]
    linhas = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
    assert linhas[0][:3] == ["Quando", "Pessoa", "Chamado"] and len(linhas) == 2
    r = client.get("/relatorios/csv", params={**filtros, "aba": "produtividade", "bloco": "3"})
    linhas = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
    assert linhas == [
        [
            "Pessoa",
            "Horas",
            "Horas (min)",
            "Horas extras",
            "Horas extras (min)",
            "Tarefas",
            "Chamados concluídos",
        ],
        ["Ana", "2,00", "120", "1,00", "60", "2", "0"],
        ["Total", "2,00", "120", "1,00", "60", "2", "0"],
    ]
    assert client.get("/relatorios/csv", params={**filtros, "bloco": "9"}).status_code == 404
    registro = db.scalars(
        select(AuditLog).where(AuditLog.action == "report.exported").order_by(AuditLog.id)
    ).all()[-1]
    assert (registro.after or {})["table"] == "block"


def test_linha_e_horas_em_decimal(client: TestClient, cenario: dict[str, Any]) -> None:
    dia = dia_util_passado()
    numero = registrar(client, cenario)["number"]
    tarefa(client, numero, 90, em(dia, 10))
    campos = {
        "blocos": "2",
        "b0-visual": "cards",
        "b0-medidas": ["hours"],
        "b1-visual": "line",
        "b1-agrupar": "day",
        "b1-medida": "hours",
        "b1-titulo": "Meu gráfico",
    }
    dados = formulario(client, nome="Linha", horas="decimal", acao="salvar", **campos)
    r = client.post("/relatorios/modelos", data=dados, follow_redirects=False)
    modelo = parse_qs(urlsplit(r.headers["location"]).query)["aba"][0]
    r = client.get("/relatorios/blocos", params=_um_dia(dia, aba=modelo))
    assert '<dd class="mt-1 text-2xl font-semibold">1,5 h</dd>' in r.text
    assert "<polyline" in r.text and "Meu gráfico" in r.text
    assert f'aria-label="{format_day("pt-BR", dia)}: 1,5 h"' in r.text


def test_modelo_salvo_na_versao_1_continua_abrindo(
    client: TestClient, cenario: dict[str, Any], db: Session
) -> None:
    # Na versão 1, `compare` era booleano: true é comparar com o período anterior.
    modelo = _criar(client, "Antigo")
    atual = db.scalar(select(ReportModel.config).where(ReportModel.name == "Antigo"))
    assert atual is not None and atual["version"] == 2
    for compara, opcao in ((True, "anterior"), (False, "")):
        config = {**atual, "version": 1, "period": {**atual["period"], "compare": compara}}
        db.execute(update(ReportModel).where(ReportModel.name == "Antigo").values(config=config))
        db.commit()
        r = client.get("/relatorios/blocos", params={"aba": modelo})
        assert f'<option value="{opcao}" selected>' in r.text
    # Salvo de novo, fica na versão 2.
    r = client.post(
        f"/relatorios/modelos/{modelo}",
        data=formulario(client, nome="Antigo", horas="hm", blocos="1", acao="salvar", **TABELA),
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    db.expire_all()
    salvo = db.scalar(select(ReportModel.config).where(ReportModel.name == "Antigo"))
    assert salvo is not None and salvo["version"] == 2 and salvo["period"]["compare"] == "none"


def test_filtro_salvo_que_nao_vale_mais(
    client: TestClient, cenario: dict[str, Any], db: Session
) -> None:
    modelo = _criar(client, "Antigo")
    alguem = str(uuid.uuid4())
    config = db.scalar(select(ReportModel.config).where(ReportModel.name == "Antigo"))
    assert config is not None
    config["filters"]["people"] = [alguem]
    db.execute(update(ReportModel).where(ReportModel.name == "Antigo").values(config=config))
    db.commit()
    r = client.get("/relatorios/blocos", params={"aba": modelo})
    assert "não valem mais para você e ficaram de fora: Pessoa." in r.text
    assert "Por pessoa" in r.text  # o relatório aparece, sem o filtro

    # Um formato que não vale mais: a tela avisa e o editor deixa refazer.
    db.execute(update(ReportModel).where(ReportModel.name == "Antigo").values(config={"x": 1}))
    db.commit()
    r = client.get("/relatorios/blocos", params={"aba": modelo})
    assert "Este modelo foi salvo num formato que não vale mais." in r.text
    r = client.get(f"/relatorios/modelos/{modelo}/editar")
    assert r.status_code == 200 and "Este modelo foi salvo num formato" in r.text


# --- medidas de chamados, comparar e detalhar (docs/14 §14.8, fase 3) -------------------------


def test_chamados_em_aberto_e_detalhar(
    client: TestClient, cenario: dict[str, Any], db: Session
) -> None:
    dia = dia_util_passado()
    aberto = registrar(client, cenario, title="Ainda aberto")["number"]
    fechado = registrar(client, cenario, title="Já resolvido")["number"]
    r = client.post(
        f"{API}/{fechado}/transitions",
        json={"action": "close", "comment": "Pronto", "resolution_code_id": 1},
    )
    assert r.status_code == 200, r.text
    # Os dois foram registrados 3 dias antes; o segundo, concluído no dia (data informada).
    db.execute(
        update(Ticket)
        .where(Ticket.number.in_([aberto, fechado]))
        .values(created_at=em(dia, 12) - timedelta(days=3))
    )
    db.execute(update(Ticket).where(Ticket.number == fechado).values(closed_at=em(dia, 12)))
    db.commit()

    filtros = _um_dia(dia, aba="chamados")
    r = client.get("/relatorios/blocos", params=filtros)
    assert 'aria-current="page">Chamados</a>' in r.text
    assert "Em aberto no fim" in r.text and "Mediana até a conclusão" in r.text
    assert ">3d</a></dd>" in r.text  # o tempo até a conclusão, em dias
    # O número de chamados abre a lista deles.
    lista = re.search(r'<a href="(/relatorios/chamados\?[^"]+medida=backlog)"', r.text)
    assert lista
    r = client.get(lista.group(1).replace("&amp;", "&"))
    assert "<title>Em aberto no fim · TicketFlow</title>" in r.text
    assert f'href="/chamados/{aberto}"' in r.text and f'href="/chamados/{fechado}"' not in r.text
    assert "Chamados encontrados: 1." in r.text

    # No fim da véspera, o concluído ainda estava aberto, com o status de então.
    vespera = dia - timedelta(days=1)
    r = client.get("/relatorios/chamados", params=_um_dia(vespera, medida="backlog"))
    assert f'href="/chamados/{fechado}"' in r.text and "Chamados encontrados: 2." in r.text
    assert '<td class="px-3 py-2">Pendente</td>' in r.text

    r = client.get("/relatorios/chamados", params=_um_dia(dia, medida="closed"))
    assert f'href="/chamados/{fechado}"' in r.text and "3d" in r.text
    r = client.get("/relatorios/chamados", params=_um_dia(dia, medida="closed", formato="csv"))
    linhas = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
    assert linhas[0][:2] == ["Chamado", "Título"] and linhas[1][:2] == [
        str(fechado),
        "Já resolvido",
    ]
    registro = db.scalars(
        select(AuditLog).where(AuditLog.action == "report.exported").order_by(AuditLog.id)
    ).all()[-1]
    assert (registro.after or {})["table"] == "tickets"
    assert client.get("/relatorios/chamados", params=_um_dia(dia, medida="xyz")).status_code == 404


def _registrado_ha_dias(
    client: TestClient, cenario: dict[str, Any], db: Session, status: int
) -> int:
    """Um chamado registrado 3 dias antes, já no `status` (sem evento: como se fosse antigo)."""
    numero: int = registrar(client, cenario)["number"]
    db.execute(
        update(Ticket)
        .where(Ticket.number == numero)
        .values(created_at=datetime.now(TIMEZONE) - timedelta(days=3), status_id=status)
    )
    db.commit()
    return numero


def test_em_aberto_no_fim_com_transferencia_depois(
    client: TestClient, cenario: dict[str, Any], db: Session
) -> None:
    """A transferência volta o chamado para Pendente: o status de antes conta como o do fim."""
    aguardando = int(status_id(client, "Aguardando cliente"))
    numero = _registrado_ha_dias(client, cenario, db, aguardando)
    r = client.post(
        f"{API}/{numero}/transfer",
        json={"team_id": cenario["infra"], "assignee_id": cenario["caio"], "reason": "Rede"},
    )
    assert r.status_code == 200, r.text

    # A Ana deixou de ser responsável: quem vê é o admin.
    admin = outra_sessao(client)
    criar_usuario(db, "admin@x.com", "admin")
    entrar(admin, "admin@x.com")
    ontem = datetime.now(TIMEZONE).date() - timedelta(days=1)
    r = admin.get("/relatorios/chamados", params=_um_dia(ontem, medida="backlog"))
    assert f'href="/chamados/{numero}"' in r.text
    assert '<td class="px-3 py-2">Aguardando cliente</td>' in r.text


def test_em_aberto_no_fim_num_status_removido(
    client: TestClient, cenario: dict[str, Any], db: Session
) -> None:
    """O status do fim do período foi removido depois: fica o nome da data da mudança."""
    removido = TicketStatus(name="Esperando peças", kind="waiting", sort_order=99)
    db.add(removido)
    db.commit()
    numero = _registrado_ha_dias(client, cenario, db, removido.id)
    r = client.patch(f"{API}/{numero}", json={"status_id": int(status_id(client, "Pendente"))})
    assert r.status_code == 200, r.text
    admin = outra_sessao(client)
    criar_usuario(db, "admin@x.com", "admin")
    entrar(admin, "admin@x.com")
    assert admin.delete(f"/api/v1/statuses/{removido.id}").status_code == 200

    ontem = datetime.now(TIMEZONE).date() - timedelta(days=1)
    r = client.get("/relatorios/chamados", params=_um_dia(ontem, medida="backlog"))
    assert r.status_code == 200
    assert '<td class="px-3 py-2">Esperando peças</td>' in r.text
    r = client.get("/relatorios/blocos", params=_um_dia(ontem, aba="chamados"))
    assert r.status_code == 200


def test_comparar_e_detalhar_por_linha(client: TestClient, cenario: dict[str, Any]) -> None:
    dia = dia_util_passado()
    numero = registrar(client, cenario)["number"]
    tarefa(client, numero, 60, em(dia, 10))
    tarefa(client, numero, 30, em(dia - timedelta(days=1), 10))

    r = client.get("/relatorios/blocos", params=_um_dia(dia, comparar="1"))
    anterior = format_day("pt-BR", dia - timedelta(days=1))
    assert f"comparado com {anterior} a {anterior}" in r.text
    assert "+100% · antes: 30min" in r.text  # 1h contra 30min
    # O "comparar=1" dos links antigos é o período anterior.
    assert '<option value="anterior" selected>O período anterior</option>' in r.text
    (aba,) = _links(r.text, "Clientes")
    assert "comparar=anterior" in aba

    # A coluna do dia aplica o dia como período; a barra da pessoa, a pessoa.
    de = f"de={dia.isoformat()}&amp;ate={dia.isoformat()}"
    assert re.search(
        rf'<a href="/relatorios\?[^"]*periodo=personalizado&amp;{de}[^"]*" hx-boost="true"'
        " aria-label",
        r.text,
    )
    assert f"pessoa={cenario['ana']}" in r.text


def test_colunas_empilhadas_e_idade_no_editor(client: TestClient, cenario: dict[str, Any]) -> None:
    dados = formulario(client, nome="X", horas="hm", acao="atualizar", blocos="1")
    r = client.post("/relatorios/modelos", data={**dados, "b0-visual": "bars"})
    assert '<option value="age">Idade</option>' in r.text
    r = client.post("/relatorios/modelos", data={**dados, "b0-visual": "stacked"})
    assert 'name="b0-medida"' not in r.text and "uma sobre a outra" in r.text

    dia = dia_util_passado()
    numero = registrar(client, cenario)["number"]
    tarefa(client, numero, 90, em(dia, 19))  # 60 min fora do expediente
    campos = {"b0-visual": "stacked", "b0-agrupar": "day"}
    modelo = _criar(client, "Empilhadas", **{**campos, "b0-medidas": []})
    r = client.get("/relatorios/blocos", params=_um_dia(dia, aba=modelo))
    assert "Horas por dia: no expediente e extras" in r.text
    assert "No expediente: 30min · Horas extras: 1h" in r.text
    assert "fill-chart-2" in r.text


# --- PDF do modelo e relatório para o cliente (docs/14 §14.8, fase 4) ------------------------


def _capturar(monkeypatch: pytest.MonkeyPatch, nome: str) -> list[tuple[Any, ...]]:
    """Troca o desenho do PDF por um que guarda o que recebeu."""
    chamadas: list[tuple[Any, ...]] = []

    def desenhar(*args: Any) -> bytes:
        chamadas.append(args)
        return b"%PDF-teste"

    monkeypatch.setattr(model_pdf, nome, desenhar)
    return chamadas


def _link_pdf(html: str) -> str:
    achado = re.search(r'<a href="(/relatorios/pdf\?[^"]+)" download', html)
    assert achado, "sem o link do PDF do modelo"
    return achado.group(1).replace("&amp;", "&")


def test_pdf_do_modelo(
    client: TestClient, cenario: dict[str, Any], db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    dia = dia_util_passado()
    numero = registrar(client, cenario)["number"]
    tarefa(client, numero, 90, em(dia, 19))
    campos = {
        "blocos": "3",
        "b0-visual": "cards",
        "b0-medidas": ["hours", "closed"],
        "b1-visual": "stacked",
        "b1-agrupar": "day",
        "b2-visual": "table",
        "b2-agrupar": "person",
        "b2-medidas": ["hours"],
    }
    dados = formulario(client, nome="Mensal", horas="hm", acao="salvar", **campos)
    r = client.post("/relatorios/modelos", data=dados, follow_redirects=False)
    modelo = parse_qs(urlsplit(r.headers["location"]).query)["aba"][0]

    # Todas as abas, inclusive as de horas, baixam o PDF do modelo (a API continua com o dela).
    for aba in ("produtividade", "chamados"):
        r = client.get("/relatorios/blocos", params={"aba": aba})
        assert "/relatorios/pdf?" in r.text and "/api/v1/reports/pdf" not in r.text
    r = client.get("/relatorios/blocos", params=_um_dia(dia, aba=modelo, comparar="1"))
    assert client.get(_link_pdf(r.text)).content.startswith(b"%PDF-1")  # desenhado de verdade
    chamadas = _capturar(monkeypatch, "render_model")
    r = client.get(_link_pdf(r.text))
    assert r.status_code == 200 and r.content == b"%PDF-teste"
    assert r.headers["content-type"] == "application/pdf"
    titulo, linhas, blocos, pagina, cores, calor = chamadas[0]
    assert calor == ("#EDC3B5", "#E5A490", "#DB856A", "#CF6543", "#C2410C")
    assert titulo == "Mensal"
    assert cores == {
        "chart-1": "#C2410C",
        "chart-2": "#1D4ED8",
        "chart-3": "#0F766E",
        "chart-4": "#172554",
        "chart-before": "#D3785C",
    }
    anterior = (dia - timedelta(days=1)).strftime("%d/%m/%Y")
    assert linhas[0] == f"Período: {dia:%d/%m/%Y} a {dia:%d/%m/%Y}"
    assert linhas[1] == f"Comparado com {anterior} a {anterior}"
    assert [type(b).__name__ for b in blocos] == ["Cards", "Chart", "Grid"]
    assert blocos[0].items[0][:2] == ("Horas", "1h30")
    assert blocos[1].kind == "stacked" and blocos[1].points[0][1:3] == (90, 60)
    # Comparando, a tabela tem a variação (sem base: vazia), com uma abreviatura no lugar do Δ.
    assert blocos[2].columns == ["Pessoa", "Horas", "Var."]
    assert blocos[2].rows == [["Ana", "1h30", ""]] and blocos[2].total == ["1h30", ""]
    # O rodapé de cada página: quando e quem gerou, e o número da página.
    assert pagina.generated.endswith("por Ana") and pagina.numbering == "Página {n} de {total}"
    assert (pagina.footer, pagina.landscape) == ("", False)
    registro = db.scalars(
        select(AuditLog).where(AuditLog.action == "report.exported").order_by(AuditLog.id)
    ).all()[-1]
    assert (registro.after or {})["format"] == "pdf" and (registro.after or {})["table"] == "model"


def _folha(html: str) -> str:
    """A folha da prévia do relatório para o cliente."""
    achado = re.search(r"<article .*?</article>", html, re.S)
    assert achado, "sem a folha"
    return achado.group(0)


def test_relatorio_para_o_cliente(
    client: TestClient, cenario: dict[str, Any], db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    padaria = criar_cliente(db, "Padaria Pão Quente", "11222333000181")
    dia = dia_util_passado()
    numero = registrar(client, cenario, client_id=padaria, title="Impressora")["number"]
    tarefa(client, numero, 90, em(dia, 19))
    registrar(client, cenario, title="De outro cliente")

    # No editor, o público "cliente" esconde os blocos (guardados) e oferece "quem atendeu".
    dados = formulario(client, nome="X", horas="hm", acao="atualizar", blocos="1", publico="client")
    r = client.post("/relatorios/modelos", data={**dados, **TABELA})
    assert '<div class="flex flex-col gap-4" hidden>' in r.text
    assert 'name="atendeu"' in r.text and "tem a abertura, os totais" in r.text
    modelo = _criar(client, "Para a padaria", publico="client", atendeu="1")

    # Sem um cliente (só um) no filtro, a tela avisa e não há PDF.
    r = client.get("/relatorios/blocos", params=_um_dia(dia, aba=modelo))
    assert "precisa de um cliente, e só um" in r.text and "/relatorios/pdf?" not in r.text
    r = client.get(
        "/relatorios/blocos", params=_um_dia(dia, aba=modelo, cliente=[padaria, "sem-cliente"])
    )
    assert "precisa de um cliente, e só um" in r.text

    filtros = _um_dia(dia, aba=modelo, cliente=padaria)
    r = client.get("/relatorios/blocos", params=filtros)
    assert "Prévia do relatório para Padaria Pão Quente:" in r.text
    # Uma folha A4 de papel branco (também no modo escuro), com o cabeçalho, os totais, os
    # chamados e o rodapé do PDF; sem logotipo nas Configurações, sem imagem.
    folha = _folha(r.text)
    assert "aspect-[210/297]" in folha and "bg-paper" in folha and "font-paper" in folha
    assert ">Relatório de atendimento</h2>" in folha and "<p>Padaria Pão Quente</p>" in folha
    assert f">#{numero}</td>" in folha and "De outro cliente" not in folha
    assert ">Atendido por</th>" in folha and ">Horas extras</th>" not in folha
    assert ">Gerado em " in folha and "<img" not in folha

    assert client.get(_link_pdf(r.text)).content.startswith(b"%PDF-1")  # desenhado de verdade
    # O PDF leva o logotipo da instalação.
    db.add(
        SystemSetting(
            key="logo", value={"data": "aGVsbG8=", "content_type": "image/png", "sha256": "x"}
        )
    )
    db.commit()
    chamadas = _capturar(monkeypatch, "render_client")
    r = client.get(_link_pdf(r.text))
    assert r.status_code == 200
    logo, titulo, linhas, abertura, totais, chamados, observacoes, pagina = chamadas[0]
    assert abertura == observacoes == ""  # sem os textos, nada
    assert logo == b"hello" and titulo == "Relatório de atendimento"
    assert linhas[0] == "Padaria Pão Quente" and linhas[1].startswith("Período:")
    assert totais[0] == ("Horas", "1h30")
    assert chamados.columns[-1] == "Atendido por"
    assert chamados.rows[0][0] == f"#{numero}" and chamados.rows[0][-1] == "Ana"
    assert "Ana" not in pagina.generated  # sem o nome de quem gerou
    # A prévia: os mesmos textos, e o logotipo como nas Configurações.
    folha = _folha(client.get("/relatorios/blocos", params=filtros).text)
    assert f"<p>{linhas[1]}</p>" in folha and f">{titulo}</h2>" in folha
    assert '<img src="/api/v1/branding/logo?v=x"' in folha
    sem_cliente = client.get("/relatorios/pdf", params=_um_dia(dia, aba=modelo))
    assert sem_cliente.status_code == 422


def test_aba_clientes(
    client: TestClient, cenario: dict[str, Any], db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A aba Clientes abre só com os concluídos; o PDF é o simplificado (os blocos) ou o
    detalhado (as tarefas de cada cliente, e os blocos como o resumo). A hora extra, por padrão,
    não aparece; escolhida "separada", vem ao lado do tempo no expediente."""
    dia = dia_util_passado()
    padaria = criar_cliente(db, "Padaria Pão Quente", "11222333000181")
    mercado = criar_cliente(db, "Mercado Bom Preço", "11444777000161")
    numeros = {
        titulo: registrar(client, cenario, title=titulo, client_id=cliente)["number"]
        for titulo, cliente in (
            ("Forno parado", padaria),
            ("Caixa travado", mercado),
            ("Ainda aberto", padaria),
        )
    }
    tarefa(client, numeros["Forno parado"], 90, em(dia, 10))
    tarefa(client, numeros["Forno parado"], 30, em(dia + timedelta(days=1), 10))
    tarefa(client, numeros["Caixa travado"], 90, em(dia, 19))  # 1h fora do expediente
    tarefa(client, numeros["Ainda aberto"], 60, em(dia, 14))
    for titulo in ("Forno parado", "Caixa travado"):
        r = client.post(
            f"{API}/{numeros[titulo]}/transitions",
            json={"action": "close", "comment": "Pronto", "resolution_code_id": 1},
        )
        assert r.status_code == 200, r.text
    fechado = status_id(client, "Concluído")

    # Sem filtro na URL, valem os concluídos (o filtro salvo da aba); o link da aba, vindo de
    # outra sem status, também os leva. Com um filtro na URL, vale o dela.
    r = client.get("/relatorios/blocos", params={"aba": "clientes"})
    assert parse_qs(urlsplit(_link_pdf(r.text)).query)["status"] == [fechado]
    r = client.get("/relatorios/blocos", params={"aba": "produtividade"})
    assert "PDF simplificado" not in r.text and "PDF detalhado" not in r.text
    achado = re.search(r'<a href="(/relatorios\?[^"]*aba=clientes[^"]*)"', r.text)
    assert achado, "sem a aba Clientes"
    aba = parse_qs(urlsplit(achado.group(1).replace("&amp;", "&")).query)
    assert aba["status"] == [fechado]
    r = client.get("/relatorios/blocos", params={"aba": "clientes", "periodo": "mes-atual"})
    assert "status" not in parse_qs(urlsplit(_link_pdf(r.text)).query)

    # O menu Baixar: o PDF simplificado e o detalhado, com os mesmos filtros.
    filtros = {
        "aba": "clientes",
        "periodo": "personalizado",
        "de": dia.isoformat(),
        "ate": (dia + timedelta(days=1)).isoformat(),
        "status": fechado,
    }
    r = client.get("/relatorios/blocos", params=filtros)
    (simplificado,) = _links(r.text, "PDF simplificado")
    (detalhado,) = _links(r.text, "PDF detalhado (tarefas de cada cliente)")
    assert parse_qs(urlsplit(detalhado).query) == {
        **parse_qs(urlsplit(simplificado).query),
        "detalhado": ["1"],
    }
    assert client.get(detalhado).content.startswith(b"%PDF-1")  # desenhado de verdade
    registro = db.scalars(
        select(AuditLog).where(AuditLog.action == "report.exported").order_by(AuditLog.id)
    ).all()[-1]
    assert (registro.after or {})["table"] == "detailed"

    chamadas = _capturar(monkeypatch, "render_model")
    client.get(simplificado)
    client.get(detalhado)
    (_, _, simples, *_), (_, _, blocos, *_) = chamadas
    assert isinstance(simples[0], model_pdf.Cards) and simples[0].title == ""
    # Um cliente por tabela, pelo nome; cada tarefa com o dia, o chamado, as horas no plano e as
    # excedentes (sem contrato, todas) e o tempo, e o total. O chamado em aberto fica de fora,
    # como no resumo.
    (mercado_, padaria_), resumo = blocos[:2], blocos[2:]
    assert isinstance(mercado_, model_pdf.Grid) and isinstance(padaria_, model_pdf.Grid)
    assert (mercado_.title, padaria_.title) == ("Mercado Bom Preço", "Padaria Pão Quente")
    assert mercado_.columns == [
        "Quando", "Chamado", "Horas no plano", "Horas excedentes", "Tempo"
    ]  # fmt: skip
    um, dois = dia.strftime("%d/%m/%Y"), (dia + timedelta(days=1)).strftime("%d/%m/%Y")
    caixa = f"#{numeros['Caixa travado']} Caixa travado"
    assert mercado_.rows == [[um, caixa, "0min", "1h30", "1h30"]]
    assert padaria_.rows == [
        [um, f"#{numeros['Forno parado']} Forno parado", "0min", "1h30", "1h30"],
        [dois, f"#{numeros['Forno parado']} Forno parado", "0min", "30min", "30min"],
    ]
    assert (padaria_.total_label, padaria_.total) == ("Total", ["", "0min", "2h", "2h"])
    # No fim, os blocos do simplificado, com o título do resumo. Sem a hora extra: nem nos
    # cartões, nem a frase do expediente no cabeçalho.
    assert len(resumo) == len(simples) and resumo[0].title == "Resumo do período"
    assert isinstance(resumo[0], model_pdf.Cards)
    assert "Horas extras" not in [rotulo for rotulo, _, _ in resumo[0].items]
    assert not any(linha.startswith("Hora extra é") for linha in chamadas[1][1])

    # O seletor da hora extra fica ao lado do Comparar, só nesta aba; o padrão é sem separação.
    r = client.get("/relatorios/blocos", params=filtros)
    assert '<select id="campo-extras" name="extras"' in r.text
    assert '<option value="" selected>Sem separação</option>' in r.text
    assert not re.search(r"<dt[^>]*>Horas (extras|no expediente)</dt>", r.text)
    outra = client.get("/relatorios/blocos", params={**filtros, "aba": "produtividade"})
    assert 'name="extras"' not in outra.text
    # Separada: as horas no expediente e as extras na tela e nos PDFs (a soma das duas é o
    # tempo), com a frase do expediente no cabeçalho.
    r = client.get("/relatorios/blocos", params={**filtros, "extras": "separada"})
    assert '<option value="separada" selected>Separada</option>' in r.text
    assert re.search(r"<dt[^>]*>Horas no expediente</dt>", r.text)
    assert re.search(r"<dt[^>]*>Horas extras</dt>", r.text)
    (detalhado,) = _links(r.text, "PDF detalhado")
    assert parse_qs(urlsplit(detalhado).query)["extras"] == ["separada"]
    client.get(detalhado)
    _, linhas, blocos, *_ = chamadas[-1]
    assert any(linha.startswith("Hora extra é") for linha in linhas)
    mercado_ = blocos[0]
    assert isinstance(mercado_, model_pdf.Grid)
    assert mercado_.columns == [
        "Quando",
        "Chamado",
        "Horas no expediente",
        "Horas extras",
        "Horas no plano",
        "Horas excedentes",
        "Tempo",
    ]
    assert mercado_.rows == [[um, caixa, "30min", "1h", "0min", "1h30", "1h30"]]
    assert mercado_.total == ["", "30min", "1h", "0min", "1h30", "1h30"]
    resumo = blocos[2]
    assert isinstance(resumo, model_pdf.Cards)
    assert [rotulo for rotulo, _, _ in resumo.items][:3] == [
        "Horas", "Horas no expediente", "Horas extras"
    ]  # fmt: skip


def test_aba_clientes_plano_do_contrato(
    client: TestClient, cenario: dict[str, Any], db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """As horas além do plano vêm separadas: o mensal por mês do calendário, o anual por ano,
    com todo o trabalho feito para o cliente (o de antes do período e o que a pessoa não vê
    também consomem), na ordem em que as tarefas terminaram. Avulso e sem cliente: tudo
    excedente. As horas descontadas da tela (com um cliente só) abatem do excedente."""
    padrao = cenario["cliente"]
    mercado = criar_cliente(db, "Mercado Bom Preço", "11444777000161")
    loja = criar_cliente(db, "Loja Avulsa", "11222333000181")
    for public_id, tipo, horas in (
        (padrao, "monthly", 2),
        (mercado, "annual", 3),
        (loja, "on_demand", None),
    ):
        db.execute(
            update(Client)
            .where(Client.public_id == public_id)
            .values(contract_type=tipo, contract_hours=horas)
        )
    db.commit()
    numeros: dict[str | None, int] = {
        cliente: registrar(client, cenario, title=titulo, client_id=cliente)["number"]
        for titulo, cliente in (("Rede", padrao), ("Caixa", mercado), ("Vitrine", loja))
    }
    # Sem cliente (os chamados antigos): o cliente sai no banco.
    numeros[None] = registrar(client, cenario, title="Interno")["number"]
    db.execute(update(Ticket).where(Ticket.number == numeros[None]).values(client_id=None))
    db.commit()
    bia = outra_sessao(client)
    entrar(bia, "bia@x.com")
    # Mensal de 2h: fevereiro é outro mês; a tarefa da Bia (que a Ana não vê) já gasta 1h30 de
    # março, antes do período.
    tarefa(client, numeros[padrao], 90, em(date(2026, 2, 27), 10))
    tarefa(bia, numeros[padrao], 90, em(date(2026, 3, 2), 10))
    tarefa(client, numeros[padrao], 60, em(date(2026, 3, 3), 10))  # 30min no plano
    tarefa(client, numeros[padrao], 45, em(date(2026, 3, 4), 10))  # toda excedente
    # Anual de 3h: 2025 é outro ano; janeiro já gasta 2h30.
    tarefa(client, numeros[mercado], 200, em(date(2025, 12, 30), 10))
    tarefa(client, numeros[mercado], 150, em(date(2026, 1, 15), 10))
    tarefa(client, numeros[mercado], 60, em(date(2026, 3, 3), 14))  # 30min no plano
    tarefa(client, numeros[loja], 40, em(date(2026, 3, 3), 15))
    tarefa(client, numeros[None], 20, em(date(2026, 3, 4), 16))

    chamadas = _capturar(monkeypatch, "render_model")
    filtros = {
        "aba": "clientes",
        "periodo": "personalizado",
        "de": "2026-03-03",
        "ate": "2026-03-04",
    }
    assert client.get("/relatorios/pdf", params={**filtros, "detalhado": "1"}).status_code == 200
    _, _, blocos, *_ = chamadas[-1]
    tabelas = {b.title: (b.rows, b.total) for b in blocos if isinstance(b, model_pdf.Grid)}
    assert tabelas["Cliente Padrão"] == (
        [
            ["03/03/2026", f"#{numeros[padrao]} Rede", "30min", "30min", "1h"],
            ["04/03/2026", f"#{numeros[padrao]} Rede", "0min", "45min", "45min"],
        ],
        ["", "30min", "1h15", "1h45"],
    )
    assert tabelas["Mercado Bom Preço"][1] == ["", "30min", "30min", "1h"]
    assert tabelas["Loja Avulsa"][1] == ["", "0min", "40min", "40min"]
    assert tabelas["Sem cliente"][1] == ["", "0min", "20min", "20min"]
    resumo = next(b for b in blocos if isinstance(b, model_pdf.Cards))
    valores = {rotulo: valor for rotulo, valor, _ in resumo.items}
    assert (valores["Horas"], valores["Horas no plano"], valores["Horas excedentes"]) == (
        "3h45",
        "1h",
        "2h45",
    )
    assert "Horas descontadas" not in valores

    # As horas descontadas: o campo só aparece com um cliente só; o desconto abate os primeiros
    # excedentes do período, e a tela ganha o desconto e o excedente a cobrar.
    r = client.get("/relatorios/blocos", params=filtros)
    assert 'name="desconto"' not in r.text
    um_cliente = {**filtros, "cliente": padrao}
    r = client.get("/relatorios/blocos", params=um_cliente)
    assert '<input id="campo-desconto" name="desconto" value=""' in r.text
    r = client.get("/relatorios/blocos", params={**um_cliente, "desconto": "1h"})
    assert re.search(r"<dt[^>]*>Excedente a cobrar</dt>", r.text)
    (detalhado,) = _links(r.text, "PDF detalhado")
    assert parse_qs(urlsplit(detalhado).query)["desconto"] == ["1h"]
    client.get(detalhado)
    _, _, blocos, *_ = chamadas[-1]
    padrao_ = blocos[0]
    assert isinstance(padrao_, model_pdf.Grid)
    assert padrao_.columns == [
        "Quando",
        "Chamado",
        "Horas no plano",
        "Horas excedentes",
        "Horas descontadas",
        "Excedente a cobrar",
        "Tempo",
    ]
    assert [linha[2:] for linha in padrao_.rows] == [
        ["30min", "30min", "30min", "0min", "1h"],
        ["0min", "45min", "30min", "15min", "45min"],
    ]
    assert padrao_.total == ["", "30min", "1h15", "1h", "15min", "1h45"]
    resumo = next(b for b in blocos if isinstance(b, model_pdf.Cards))
    valores = {rotulo: valor for rotulo, valor, _ in resumo.items}
    assert (valores["Horas descontadas"], valores["Excedente a cobrar"]) == ("1h", "15min")
    # O que não se entende fica de fora, com o aviso.
    r = client.get("/relatorios/blocos", params={**um_cliente, "desconto": "uma hora"})
    assert "Use horas e minutos, ex.: 2:30." in r.text
    assert not re.search(r"<dt[^>]*>Excedente a cobrar</dt>", r.text)


@pytest.mark.parametrize(
    ("texto", "minutos"),
    [("2:30", 150), ("2h30", 150), ("2h", 120), ("2", 120), ("0:05", 5), ("45min", 45)],
)
def test_horas_descontadas_aceitas(texto: str, minutos: int) -> None:
    assert parse_minutes(texto) == minutos


@pytest.mark.parametrize("texto", ["2:75", "duas", "2,5", "-1"])
def test_horas_descontadas_recusadas(texto: str) -> None:
    assert parse_minutes(texto) is None


def _com_blocos(client: TestClient, url: str) -> Any:
    """Um link da tela, como o navegador o segue: a página e, nela, o pedido dos números."""
    pagina = client.get(url)
    achado = re.search(r'<div id="blocos" hx-get="([^"]+)" hx-trigger="load"', pagina.text)
    assert achado, "sem o pedido dos números"
    return client.get(achado.group(1).replace("&amp;", "&"))


def _links(html: str, texto: str) -> list[str]:
    """Os endereços dos links cujo texto ou aria-label tem `texto`, já sem o &amp;."""
    achados = re.findall(rf'<a href="([^"]+)"[^>]*>(?:(?!</a>).)*{re.escape(texto)}', html, re.S)
    achados += re.findall(rf'<a href="([^"]+)"[^>]*aria-label="[^"]*{re.escape(texto)}', html)
    return [a.replace("&amp;", "&") for a in achados]


def test_abas_logo_abaixo_do_titulo(client: TestClient, cenario: dict[str, Any]) -> None:
    r = client.get("/relatorios/blocos")
    assert r.text.index('<nav aria-label="Modelos') < r.text.index('<form method="get"')


def test_resumo_dos_filtros_e_limpar(client: TestClient, cenario: dict[str, Any]) -> None:
    entrar(client, "bia@x.com")
    r = client.get(
        "/relatorios/blocos", params={"pessoa": cenario["ana"], "cliente": "sem-cliente"}
    )
    assert "Filtrado por:" in r.text
    # Cada × tira só aquele valor; o período continua.
    (tira_ana,) = _links(r.text, "Tirar Ana")
    query = parse_qs(urlsplit(tira_ana).query)
    assert "pessoa" not in query and query["cliente"] == ["sem-cliente"]
    assert query["periodo"] == ["mes-atual"] and query["aba"] == ["produtividade"]
    # "Limpar" tira todos e manda o período, para não cair nos filtros salvos.
    (limpar,) = _links(r.text, "Limpar filtros")
    assert parse_qs(urlsplit(limpar).query) == {"periodo": ["mes-atual"], "aba": ["produtividade"]}
    assert "Filtrado por:" not in client.get(limpar).text

    # Num modelo com filtro salvo, "Limpar" fica no modelo e não traz o salvo de volta.
    modelo = _criar(client, "Sem cliente", periodo="ultimos-7-dias", cliente="sem-cliente")
    r = client.get("/relatorios/blocos", params={"aba": modelo})
    (limpar,) = _links(r.text, "Limpar filtros")
    r = client.get(limpar)
    assert '<option value="ultimos-7-dias" selected>' in r.text
    assert 'name="cliente" value="sem-cliente"' not in r.text
    assert "Salvar filtros" in r.text


def test_restaurar_filtros_salvos(client: TestClient, cenario: dict[str, Any]) -> None:
    modelo = _criar(client, "Semana", periodo="ultimos-7-dias")
    # Com os filtros salvos, nada a restaurar.
    r = client.get("/relatorios/blocos", params={"aba": modelo})
    assert "Restaurar filtros salvos" not in r.text
    # Mexer num filtro mostra "Salvar filtros" e o link que volta aos salvos.
    r = client.get("/relatorios/blocos", params={"aba": modelo, "periodo": "mes-anterior"})
    assert "Salvar filtros" in r.text
    assert _links(r.text, "Restaurar filtros salvos") == [f"/relatorios?aba={modelo}"]
    # Nos modelos prontos não há o que restaurar.
    r = client.get("/relatorios/blocos", params={"periodo": "mes-anterior"})
    assert "Restaurar filtros salvos" not in r.text


def test_trilha_do_detalhar(client: TestClient, cenario: dict[str, Any]) -> None:
    hoje = datetime.now(TIMEZONE).date()
    r = client.get("/relatorios/blocos", params={"periodo": "mes-atual"})
    # A coluna de um dia aplica o dia como período e leva o de antes como origem.
    dia = hoje.isoformat()
    coluna = next(u for u in _links(r.text, format_day("pt-BR", hoje)) if f"de={dia}" in u)
    assert parse_qs(urlsplit(coluna).query)["origem"] == ["mes-atual"]

    r = client.get(coluna)
    assert f"Detalhando de {format_day('pt-BR', hoje)} a {format_day('pt-BR', hoje)}." in r.text
    (voltar,) = _links(r.text, "Voltar para Mês atual")
    query = parse_qs(urlsplit(voltar).query)
    assert query["periodo"] == ["mes-atual"]
    assert "de" not in query and "origem" not in query
    # O formulário leva a origem: mexer nos outros filtros mantém a trilha.
    assert '<input type="hidden" name="origem" value="mes-atual">' in r.text

    # Detalhar a partir de um personalizado volta às duas datas.
    r = client.get(coluna.replace("origem=mes-atual", "origem=2026-01-01_2026-01-31"))
    (voltar,) = _links(r.text, "Voltar para")
    query = parse_qs(urlsplit(voltar).query)
    assert (query["de"], query["ate"]) == (["2026-01-01"], ["2026-01-31"])
    # Origem desconhecida, ou fora do personalizado: sem trilha.
    assert "Detalhando" not in client.get(coluna.replace("mes-atual", "xyz")).text
    r = client.get("/relatorios/blocos", params={"periodo": "mes-atual", "origem": "mes-anterior"})
    assert "Detalhando" not in r.text


def test_filtros_pelo_htmx(client: TestClient, cenario: dict[str, Any], db: Session) -> None:
    padaria = criar_cliente(db, "Padaria Pão Quente", "11222333000181")
    numero = registrar(client, cenario, client_id=padaria)["number"]
    tarefa(client, numero, 30, em(dia_util_passado(), 10))
    # Com o período na URL, sem o filtro salvo da aba (só os concluídos): o chamado está aberto.
    r = client.get("/relatorios/blocos", params={"aba": "clientes", "periodo": "mes-atual"})
    # O formulário troca o #relatorio (cabeçalho, filtros, abas e blocos) esperando as escolhas
    # seguidas, com o endereço na barra; um pedido novo cancela o anterior.
    assert (
        '<div id="relatorio" hx-target="#relatorio" hx-select="#relatorio" hx-swap="outerHTML"'
        ' hx-indicator="#relatorio"' in r.text
    )
    assert (
        'hx-get="/relatorios" hx-trigger="submit delay:600ms" hx-push-url="true"'
        ' hx-sync="this:replace"' in r.text
    )
    # O aviso para o leitor de tela fica fora da região trocada; o "Carregando…" dentro.
    assert r.text.index('id="relatorio-aviso"') < r.text.index('<div id="relatorio"')
    assert "Carregando…" in r.text and 'data-texto="Relatório atualizado."' in r.text
    # O Comparar tem id: a tela nova devolve o foco a ele.
    assert '<select id="campo-comparar" name="comparar"' in r.text
    # As abas e o detalhar vão pelo HTMX; a lista de chamados e os downloads, não.
    assert '<nav aria-label="Modelos de relatório" hx-boost="true"' in r.text
    assert 'hx-boost="true" class="hover:underline">Padaria Pão Quente</a>' in r.text
    assert not re.search(r'<a href="/relatorios/(chamados|csv)[^"]*" hx-boost', r.text)
    assert not re.search(r'<a href="/api/[^"]*" hx-boost', r.text)
    # O pedido do HTMX recebe a página inteira (o hx-select escolhe o trecho).
    r = client.get(
        "/relatorios/blocos",
        params={"aba": "clientes", "cliente": padaria},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200 and '<div id="relatorio"' in r.text
    assert "Filtrado por:" in r.text


def test_numeros_em_segundo_plano(
    client: TestClient, cenario: dict[str, Any], db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A página sai sem os números (o título, as abas, os filtros e os downloads) e um esqueleto
    do tamanho dos blocos os pede em /relatorios/blocos, com a mesma consulta."""
    from chamados.modules.reports import service

    dia = dia_util_passado()
    padaria = criar_cliente(db, "Padaria Pão Quente", "11222333000181")
    numero = registrar(client, cenario, client_id=padaria)["number"]
    tarefa(client, numero, 90, em(dia, 19))
    calculos: list[Any] = []
    facts = service.facts

    async def contar(*args: Any, **kwargs: Any) -> Any:
        calculos.append(args)
        return await facts(*args, **kwargs)

    monkeypatch.setattr(service, "facts", contar)
    filtros = _um_dia(dia, aba="horas-extras", pagina3="2")
    r = client.get("/relatorios", params=filtros)
    assert r.status_code == 200 and not calculos
    query = urlencode(filtros).replace("&", "&amp;")  # a mesma consulta, na mesma ordem
    url = f"/relatorios/blocos?{query}"
    assert (
        f'<div id="blocos" hx-get="{url}" hx-trigger="load" hx-target="this"'
        ' hx-select="#blocos" hx-swap="outerHTML" aria-busy="true"' in r.text
    )
    # Um esqueleto por bloco, com o id para onde a paginação da lista rola; sem JavaScript, o
    # link dos números.
    cartoes = 'id="bloco-0" class="scroll-mt-4 animate-pulse rounded-lg bg-surface-raised h-44'
    assert f'{cartoes} lg:col-span-2"' in r.text  # os cartões, na linha inteira
    assert all(f'id="bloco-{i}"' in r.text for i in range(4))
    assert f'<noscript><p><a href="{url}" class="text-primary underline">' in r.text
    # O cabeçalho não depende dos números: os downloads e os filtros já vêm.
    assert _pdf(r.text)["start"] == [dia.isoformat()]
    assert "Tarefas fora do expediente" not in r.text

    r = client.get(url.replace("&amp;", "&"))
    assert len(calculos) == 1
    assert '<div id="blocos" class="flex flex-col gap-4">' in r.text
    assert "Tarefas fora do expediente" in r.text and "animate-pulse" not in r.text
    assert f'href="/chamados/{numero}"' in r.text

    # Com erro (outra pessoa, para a Ana), nem esqueleto nem pedido.
    r = client.get("/relatorios", params=_um_dia(dia, pessoa=cenario["bia"]))
    assert "Você só pode ver os seus próprios números." in r.text
    assert 'id="blocos"' not in r.text

    # O modelo para o cliente: sem um cliente, o aviso vem na hora; com um, o esqueleto.
    modelo = _criar(client, "Para a padaria", publico="client")
    r = client.get("/relatorios", params=_um_dia(dia, aba=modelo))
    assert "precisa de um cliente, e só um" in r.text and 'hx-trigger="load"' not in r.text
    r = client.get("/relatorios", params=_um_dia(dia, aba=modelo, cliente=padaria))
    assert 'hx-trigger="load"' in r.text and "/relatorios/pdf?" in r.text
    r = _com_blocos(
        client,
        f"/relatorios?aba={modelo}&cliente={padaria}&periodo=personalizado&de={dia}&ate={dia}",
    )
    assert "Prévia do relatório para Padaria Pão Quente:" in r.text


def _datas(inicio: date, fim: date) -> dict[str, list[str]]:
    return {"periodo": ["personalizado"], "de": [inicio.isoformat()], "ate": [fim.isoformat()]}


def test_atalhos_do_personalizado(client: TestClient, cenario: dict[str, Any]) -> None:
    hoje = datetime.now(TIMEZONE).date()
    assert "Atalhos:" not in client.get("/relatorios/blocos").text
    r = client.get("/relatorios/blocos", params={"periodo": "personalizado"})
    segunda = hoje - timedelta(days=hoje.weekday())
    (semana,) = _links(r.text, "Esta semana")
    assert parse_qs(urlsplit(semana).query)["de"] == [segunda.isoformat()]
    (passada,) = _links(r.text, "Semana passada")
    assert parse_qs(urlsplit(passada).query)["ate"] == [(segunda - timedelta(days=1)).isoformat()]
    # Os meses inteiros são os da lista.
    (mes,) = _links(r.text, "Este mês")
    assert parse_qs(urlsplit(mes).query)["periodo"] == [f"{hoje:%Y-%m}"]
    (anterior,) = _links(r.text, "Mês passado")
    um_antes = hoje.replace(day=1) - timedelta(days=1)
    assert parse_qs(urlsplit(anterior).query)["periodo"] == [f"{um_antes:%Y-%m}"]


def test_comparar_nas_tabelas_e_nos_graficos(client: TestClient, cenario: dict[str, Any]) -> None:
    dia = dia_util_passado()
    numero = registrar(client, cenario)["number"]
    tarefa(client, numero, 60, em(dia, 10))
    tarefa(client, numero, 30, em(dia - timedelta(days=1), 10))
    delta = '<td class="px-3 py-2 text-right tabular-nums text-sm text-muted">'

    # Sem comparar, nada muda.
    r = client.get("/relatorios/blocos", params=_um_dia(dia))
    assert ">Δ</th>" not in r.text and "Período anterior</li>" not in r.text

    r = client.get("/relatorios/blocos", params=_um_dia(dia, comparar="1"))
    # A tabela ganha um Δ por medida (o nome por extenso para o leitor de tela), na linha e no
    # total, em %.
    assert 'title="Variação de Horas" aria-label="Variação de Horas">Δ</th>' in r.text
    assert 'aria-label="Variação de Horas extras">Δ</th>' in r.text
    linha = re.search(r">Ana</a></td>(.*?)</tr>", r.text, re.S)
    assert linha
    celulas = re.findall(r"<td [^>]*>(.*?)</td>", linha.group(1), re.S)
    assert celulas[:2] == ["1h", "+100%"]
    total = re.search(r"<tfoot.*?</tfoot>", r.text, re.S)
    assert total and f"{delta}+100%</td>" in total.group(0)
    # As colunas por dia ganham a série de antes, alinhada pela posição, com a legenda.
    anterior = format_day("pt-BR", dia - timedelta(days=1))
    assert f'aria-label="{format_day("pt-BR", dia)}: 1h · Antes ({anterior}): 30min"' in r.text
    assert "Período anterior</li>" in r.text
    assert 'class="max-w-5 fill-chart-before"' in r.text
    # As barras por pessoa, não.
    assert "Antes (Ana)" not in r.text

    # Sem nada no período de antes (sem base), o Δ fica vazio.
    r = client.get("/relatorios/blocos", params=_um_dia(dia - timedelta(days=1), comparar="1"))
    linha = re.search(r">Ana</a></td>(.*?)</tr>", r.text, re.S)
    assert linha
    assert re.findall(r"<td [^>]*>(.*?)</td>", linha.group(1), re.S)[:2] == ["30min", ""]

    # A linha por semana (aba Chamados): a de antes, tracejada; e o PDF a desenha.
    filtros = {
        "aba": "chamados",
        "periodo": "personalizado",
        "de": (dia - timedelta(days=20)).isoformat(),
        "ate": dia.isoformat(),
        "comparar": "1",
    }
    r = client.get("/relatorios/blocos", params=filtros)
    assert 'stroke-dasharray="4 3"' in r.text
    assert client.get(_link_pdf(r.text)).content.startswith(b"%PDF-1")


def test_comparar_com_o_ano_anterior(client: TestClient, cenario: dict[str, Any]) -> None:
    dia = dia_util_passado()
    ano = year_before(dia, dia)[0]  # a mesma data do ano anterior
    numero = registrar(client, cenario)["number"]
    tarefa(client, numero, 60, em(dia, 10))
    tarefa(client, numero, 30, em(ano, 10))
    tarefa(client, numero, 45, em(dia - timedelta(days=1), 10))  # o período anterior: fora

    r = client.get("/relatorios/blocos", params=_um_dia(dia, comparar="ano"))
    assert '<option value="ano" selected>O mesmo período do ano anterior</option>' in r.text
    antes = format_day("pt-BR", ano)
    assert f"comparado com {antes} a {antes}" in r.text
    assert "+100% · antes: 30min" in r.text
    assert "Mesmo período do ano anterior</li>" in r.text  # a legenda da série de antes
    (aba,) = _links(r.text, "Clientes")
    assert "comparar=ano" in aba

    # Semanas inteiras: as 52 semanas antes, de segunda a domingo.
    r = client.get("/relatorios/blocos", params={"periodo": "semana-anterior", "comparar": "ano"})
    segunda = dia - timedelta(weeks=52)
    texto = f"comparado com {format_day('pt-BR', segunda)} a "
    assert texto + format_day("pt-BR", segunda + timedelta(days=6)) in r.text

    # Antes do ano 1 não há com que comparar: a tela abre sem a comparação.
    r = client.get(
        "/relatorios/blocos",
        params={
            "periodo": "personalizado",
            "de": "0001-03-01",
            "ate": "0001-03-10",
            "comparar": "ano",
        },
    )
    assert r.status_code == 200 and "comparado com" not in r.text

    # O CSV do bloco leva o valor de antes e a variação de cada medida, também no total.
    filtros = _um_dia(dia, aba="produtividade", comparar="ano", bloco="3")
    r = client.get("/relatorios/csv", params=filtros)
    linhas = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
    assert linhas[0][:7] == [
        "Pessoa",
        "Horas",
        "Horas (min)",
        "Horas, antes",
        "Horas, antes (min)",
        "Variação de Horas (%)",
        "Horas extras",
    ]
    assert linhas[1][:6] == ["Ana", "1,00", "60", "0,50", "30", "100,0"]
    assert linhas[-1][:6] == ["Total", "1,00", "60", "0,50", "30", "100,0"]
    # Sem comparar, o CSV fica como era.
    filtros.pop("comparar")
    r = client.get("/relatorios/csv", params=filtros)
    assert "antes" not in r.content.decode("utf-8-sig")


def test_previa_no_editor(
    client: TestClient, cenario: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from chamados.modules.reports import service

    dia = dia_util_passado()
    numero = registrar(client, cenario)["number"]
    tarefa(client, numero, 90, em(dia, 10))
    data = format_day("pt-BR", dia)

    # Os dados do período vêm uma vez por requisição, para todos os blocos.
    facts = service.facts
    chamadas: list[Any] = []

    async def contar(*args: Any, **kwargs: Any) -> Any:
        chamadas.append(args)
        return await facts(*args, **kwargs)

    monkeypatch.setattr(service, "facts", contar)

    # Modelo novo: com o período e os filtros da tela, no lugar de cada bloco.
    r = client.get("/relatorios/modelos/novo", params=_um_dia(dia, base="produtividade"))
    assert len(chamadas) == 1
    assert r.text.count(f"Prévia, de {data} a {data}:") == 4
    assert "<div inert" in r.text and '<dd class="mt-1 text-2xl font-semibold">1h30</dd>' in r.text
    assert "Ações de" not in r.text  # na prévia, sem o menu do CSV
    # Os campos do bloco refazem o formulário (e a prévia) ao mudar; os textos, não.
    assert re.search(r'id="campo-b1-medida" name="b1-medida" hx-post="/relatorios/modelos"', r.text)
    assert 'id="campo-b0-medidas-hours"' in r.text
    assert not re.search(r'name="b\d-titulo"[^>]*hx-post', r.text)

    # Um bloco inválido mostra o erro no lugar da prévia; o formato das horas vale na prévia.
    chamadas.clear()
    dados = formulario(
        client,
        nome="X",
        horas="decimal",
        acao="atualizar",
        blocos="2",
        **{"b0-visual": "table", "b0-agrupar": "person", "b1-visual": "cards"},
        **{"b1-medidas": "hours"},
        **{k: v[0] for k, v in _datas(dia, dia).items()},
    )
    r = client.post("/relatorios/modelos", data=dados)
    assert len(chamadas) == 1
    assert '<p class="text-danger">Escolha ao menos uma medida.</p>' in r.text
    assert '<dd class="mt-1 text-2xl font-semibold">1,5 h</dd>' in r.text

    # Ao editar, com os filtros salvos no modelo.
    modelo = _criar(client, "Do dia", **{k: v[0] for k, v in _datas(dia, dia).items()})
    r = client.get(f"/relatorios/modelos/{modelo}/editar")
    assert f"Prévia, de {data} a {data}:" in r.text and ">1h30</td>" in r.text

    # Para o cliente, os blocos ficam escondidos: sem prévia (nem os dados).
    chamadas.clear()
    r = client.post("/relatorios/modelos", data={**dados, "publico": "client"})
    assert "Prévia" not in r.text and not chamadas


def test_lista_de_tarefas_em_paginas(
    client: TestClient, cenario: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from chamados.web import reports_blocks

    monkeypatch.setattr(reports_blocks, "LISTED", 2)
    dia = dia_util_passado()
    numero = registrar(client, cenario)["number"]
    for minutos in (10, 20, 30, 40, 50):
        tarefa(client, numero, minutos, em(dia, 19))  # fora do expediente
    filtros = _um_dia(dia, aba="horas-extras")
    linhas = re.compile(rf'<a href="/chamados/{numero}" class="text-primary')

    r = client.get("/relatorios/blocos", params=filtros)
    assert len(linhas.findall(r.text)) == 2
    assert "Tarefas 1 a 2 de 5. O CSV do bloco traz todas." in r.text
    # A lista de tarefas é o 4º bloco da aba (pagina3); a página leva os filtros.
    (proxima,) = _links(r.text, "Próxima")
    query = parse_qs(urlsplit(proxima).query)
    assert query["pagina3"] == ["2"] and query["aba"] == ["horas-extras"]
    assert query["de"] == [dia.isoformat()]
    assert '<button type="button" disabled' in r.text and "Anterior</button>" in r.text
    assert 'hx-swap="outerHTML show:#bloco-3:top"' in r.text

    r = _com_blocos(client, proxima)
    assert len(linhas.findall(r.text)) == 2 and "Tarefas 3 a 4 de 5." in r.text
    # Depois da última, a última; o CSV traz todas.
    r = client.get("/relatorios/blocos", params={**filtros, "pagina3": "99"})
    assert len(linhas.findall(r.text)) == 1 and "Tarefas 5 a 5 de 5." in r.text
    assert ">Próxima" in r.text and not _links(r.text, "Próxima")
    csv_ = client.get("/relatorios/csv", params={**filtros, "bloco": "3"})
    assert len(csv_.text.strip().splitlines()) == 6  # o cabeçalho e as 5

    # O cabeçalho das tabelas fica fixo ao rolar, e os números, à direita.
    assert '<thead class="sticky top-0 z-10' in r.text
    assert 'class="max-h-[70vh] overflow-auto' in r.text and "overflow-x-auto" not in r.text
    assert '<th scope="col" class="px-3 py-2 font-medium text-right">Tempo</th>' in r.text
    r = client.get("/relatorios/blocos", params=_um_dia(dia))
    assert '<th scope="col" class="px-3 py-2 font-medium text-right">Horas</th>' in r.text
    assert '<th scope="col" class="px-3 py-2 font-medium">Pessoa</th>' in r.text


def _largura(html: str) -> dict[int, bool]:
    """Os blocos da página: se cada um ocupa a linha inteira da grade."""
    blocos = re.findall(r'id="bloco-(\d+)" class="([^"]*)"', html)
    return {int(i): "lg:col-span-2" in classes for i, classes in blocos}


def test_grafico_sozinho_ocupa_a_linha(client: TestClient, cenario: dict[str, Any]) -> None:
    """Os gráficos ocupam meia linha; o último de uma sequência ímpar deles, a linha inteira (sem
    a metade vazia), como os cartões, as tabelas e as listas."""
    # Produtividade: cartões, colunas e barras (um par), tabela.
    r = client.get("/relatorios/blocos", params={"aba": "produtividade"})
    assert _largura(r.text) == {0: True, 1: False, 2: False, 3: True}
    # Clientes: as barras ficam sozinhas entre os cartões e a tabela; o esqueleto, também.
    inteiros = {0: True, 1: True, 2: True}
    for url in ("/relatorios/blocos", "/relatorios"):
        assert _largura(client.get(url, params={"aba": "clientes"}).text) == inteiros
    # Três gráficos seguidos: o terceiro; um no fim, sozinho, também.
    visuais = ["cards", "line", "line", "columns", "table", "bars"]
    assert wide(visuais) == [True, False, False, True, True, True]
    assert wide(["bars", "stacked", "line", "columns"]) == [False] * 4


def _menu_modelo(html: str) -> list[tuple[str, list[str]]]:
    """Os itens do menu Modelo do cabeçalho: o caminho e a aba de base de cada link."""
    menu = re.search(r"<summary [^>]*>Modelo <svg.*?</details>", html, re.S)
    assert menu, "sem o menu Modelo"
    links = re.findall(r'<a href="([^"]*)" role="menuitem"', menu.group(0))
    partes = [urlsplit(link.replace("&amp;", "&")) for link in links]
    return [(p.path, parse_qs(p.query).get("base", [])) for p in partes]


def test_menu_modelo(client: TestClient, cenario: dict[str, Any]) -> None:
    """Editar e salvar como modelo ficam num menu; editar, só nos modelos da pessoa."""
    r = client.get("/relatorios/blocos", params={"aba": "clientes"})
    assert _menu_modelo(r.text) == [("/relatorios/modelos/novo", ["clientes"])]
    modelo = _criar(client, "Meu", periodo="ultimos-7-dias")
    r = client.get("/relatorios/blocos", params={"aba": modelo})
    assert _menu_modelo(r.text) == [
        (f"/relatorios/modelos/{modelo}/editar", []),
        ("/relatorios/modelos/novo", [modelo]),
    ]


def _variacao(html: str, medida: str) -> str:
    """A linha da variação de um cartão (o <dd> depois do valor)."""
    achado = re.search(rf"<dt[^>]*>{medida}</dt>\s*<dd.*?</dd>\s*(<dd.*?</dd>)", html, re.S)
    assert achado, medida
    return achado.group(1)


def test_variacao_dos_cartoes(client: TestClient, cenario: dict[str, Any]) -> None:
    """A cor segue a direção boa da medida (hora extra: subir é ruim; horas: neutra); a seta e o
    texto dizem o mesmo sem a cor, e o leitor de tela ouve "Subiu" ou "Caiu"."""
    segunda = dia_util_passado()
    numero = registrar(client, cenario)["number"]
    for dia, minutos in ((segunda, 60), (segunda + timedelta(days=1), 30)):
        tarefa(client, numero, minutos, em(dia, 20))  # fora do expediente
    tarefa(client, numero, 60, em(segunda + timedelta(days=2), 20))

    # Terça contra segunda: as horas extras caíram (bom).
    r = client.get("/relatorios/blocos", params=_um_dia(segunda + timedelta(days=1), comparar="1"))
    extras = _variacao(r.text, "Horas extras")
    assert 'class="mt-1 text-sm tabular-nums text-green-fg"' in extras
    assert '<span aria-hidden="true">▼</span> <span class="sr-only">Caiu</span>' in extras
    assert "−50% · antes: 1h" in extras
    # As horas também caíram, mas são neutras.
    horas = _variacao(r.text, "Horas")
    assert "text-muted" in horas and '<span class="sr-only">Caiu</span>' in horas
    # Quarta contra terça: subiram (ruim).
    r = client.get("/relatorios/blocos", params=_um_dia(segunda + timedelta(days=2), comparar="1"))
    extras = _variacao(r.text, "Horas extras")
    assert "text-red-fg" in extras and '<span class="sr-only">Subiu</span>' in extras
    # Sem variação (as tarefas: uma e uma), nem seta nem cor.
    tarefas = _variacao(r.text, "Tarefas")
    assert "text-muted" in tarefas and "sr-only" not in tarefas


def _cartao(html: str, medida: str) -> str:
    """Um cartão inteiro, do rótulo até o fim dele."""
    achado = re.search(rf"<dt[^>]*>{medida}</dt>.*?</div>", html, re.S)
    assert achado, medida
    return achado.group(0)


def test_sparkline_nos_cartoes(client: TestClient, cenario: dict[str, Any]) -> None:
    """Cada cartão tem a tendência da medida no período, só a linha (sem eixo nem rótulos, fora
    do leitor de tela); o em aberto, que é o retrato do fim, e um período de um dia, não."""
    segunda = dia_util_passado()
    numero = registrar(client, cenario)["number"]
    tarefa(client, numero, 60, em(segunda, 10))
    tarefa(client, numero, 30, em(segunda + timedelta(days=1), 10))
    dois_dias = {
        "periodo": "personalizado",
        "de": segunda.isoformat(),
        "ate": (segunda + timedelta(days=1)).isoformat(),
    }
    r = client.get("/relatorios/blocos", params=dois_dias)
    horas = _cartao(r.text, "Horas")
    assert '<dd class="mt-2" aria-hidden="true"><svg viewBox="0 0 100 32"' in horas
    assert 'class="stroke-chart-1"' in horas and 'points="0.00,2.00 100.00,16.00"' in horas
    r = client.get("/relatorios/blocos", params={**dois_dias, "aba": "chamados"})
    assert "<polyline" in _cartao(r.text, "Chamados registrados")
    assert "<polyline" not in _cartao(r.text, "Em aberto no fim")
    r = client.get("/relatorios/blocos", params=_um_dia(segunda))
    assert "<polyline" not in _cartao(r.text, "Horas")


# --- extensão: dia da semana e hora do dia (docs/14 §14.8.3) --------------------------------


def test_dia_da_semana_e_hora_do_dia(client: TestClient, cenario: dict[str, Any]) -> None:
    segunda = dia_util_passado()
    chamado = registrar(client, cenario)
    numero = chamado["number"]
    tarefa(client, numero, 60, em(segunda, 10))
    tarefa(client, numero, 30, em(segunda + timedelta(days=1), 15))
    tarefa(client, numero, 15, em(segunda + timedelta(days=7), 10))  # outra segunda, às 10h
    modelo = _criar(
        client,
        "Ciclos",
        blocos="2",
        **{
            "b0-medidas": ["hours", "tasks"],
            "b0-agrupar": "weekday",
            "b1-visual": "columns",
            "b1-agrupar": "hour",
            "b1-medida": "hours",
        },
    )
    filtros = {
        "aba": modelo,
        "periodo": "personalizado",
        "de": segunda.isoformat(),
        "ate": (segunda + timedelta(days=7)).isoformat(),
    }
    r = client.get("/relatorios/blocos", params=filtros)
    assert "Horas por dia da semana" not in r.text  # a tabela tem o título dela
    assert "Por dia da semana" in r.text and "Horas por hora do dia" in r.text

    def linha(rotulo: str) -> list[str]:
        achado = re.search(rf"<td[^>]*>{rotulo}</td>(.*?)</tr>", r.text, re.S)
        assert achado, rotulo
        return re.findall(r"<td [^>]*>(.*?)</td>", achado.group(1), re.S)

    # Os 7 dias, na ordem, mesmo sem nada; as duas segundas somam; sem link de detalhar.
    assert linha("Segunda-feira") == ["1h15", "2"]
    assert linha("Terça-feira") == ["30min", "1"]
    assert linha("Domingo") == ["0min", "0"]
    assert r.text.index("Segunda-feira") < r.text.index("Domingo")
    # As 24 horas, a da hora de término da tarefa.
    assert 'aria-label="10h: 1h15"' in r.text and 'aria-label="15h: 30min"' in r.text
    assert 'aria-label="0h: 0min"' in r.text and 'aria-label="23h: 0min"' in r.text

    # O CSV de cada um.
    r = client.get("/relatorios/csv", params={**filtros, "bloco": "1"})
    linhas = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
    assert linhas[0][0] == "Hora do dia" and len(linhas) == 26
    assert linhas[11] == ["10:00", "1,25", "75"]
    r = client.get("/relatorios/csv", params={**filtros, "bloco": "0"})
    linhas = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
    assert linhas[1][:4] == ["segunda", "1,25", "75", "2"]

    # Comparando, a série de antes alinha pela hora.
    r = client.get("/relatorios/blocos", params={**filtros, "comparar": "anterior"})
    assert "Período anterior</li>" in r.text

    # Os registrados pela hora do registro (contados no banco).
    registro = datetime.fromisoformat(chamado["created_at"]).astimezone(TIMEZONE)
    contagem = _criar(
        client,
        "Registros por hora",
        **{"b0-medidas": ["opened"], "b0-agrupar": "hour", "b0-visual": "table"},
    )
    r = client.get("/relatorios/blocos", params=_um_dia(registro.date(), aba=contagem))
    assert linha(f"{registro.hour}h") == ["1"]


def test_editor_com_dia_da_semana_e_hora(client: TestClient, cenario: dict[str, Any]) -> None:
    # As barras e a linha não agrupam por dia da semana nem hora; o Em aberto não é oferecido.
    dados = formulario(
        client,
        nome="X",
        horas="hm",
        blocos="2",
        acao="atualizar",
        **{"b0-visual": "table", "b0-agrupar": "hour", "b1-visual": "bars"},
    )
    r = client.post("/relatorios/modelos", data=dados)
    assert '<option value="hour" selected>Hora do dia</option>' in r.text
    assert 'id="campo-b0-medidas-backlog"' not in r.text
    assert 'id="campo-b0-medidas-hours"' in r.text
    barras = re.search(r'name="b1-agrupar".*?</select>', r.text, re.S)
    assert barras and "weekday" not in barras.group(0) and "hour" not in barras.group(0)


def test_medidas_derivadas(client: TestClient, cenario: dict[str, Any], db: Session) -> None:
    segunda = dia_util_passado()
    um = registrar(client, cenario)["number"]
    dois = registrar(client, cenario)["number"]
    tarefa(client, um, 90, em(segunda, 19))  # 60 min fora do expediente
    tarefa(client, um, 30, em(segunda, 10))
    tarefa(client, dois, 60, em(segunda + timedelta(days=1), 10))
    medidas = ["overtime_rate", "hours_per_ticket", "completion_rate", "tasks_per_workday"]
    modelo = _criar(
        client,
        "Derivadas",
        blocos="3",
        **{
            "b0-visual": "cards",
            "b0-medidas": medidas,
            "b1-visual": "table",
            "b1-agrupar": "person",
            "b1-medidas": medidas,
            "b2-visual": "columns",
            "b2-agrupar": "week",
            "b2-medida": "hours_per_ticket",
        },
    )
    semana = {
        "aba": modelo,
        "periodo": "personalizado",
        "de": segunda.isoformat(),
        "ate": (segunda + timedelta(days=6)).isoformat(),
    }
    r = client.get("/relatorios/blocos", params=semana)
    # 60 de 180 min fora; 180 min em 2 chamados; nenhum registrado na semana (sem base);
    # 3 tarefas em 5 dias úteis.
    for rotulo, valor in (
        ("% de hora extra", "33,3%"),
        ("Horas por chamado", "1h30"),
        ("Taxa de conclusão", "—"),
        ("Tarefas por dia útil", "0,6"),
    ):
        assert re.search(rf"<dt[^>]*>{re.escape(rotulo)}</dt>\s*<dd[^>]*>{valor}</dd>", r.text), (
            rotulo
        )
    linha = re.search(r">Ana</a></td>(.*?)</tr>", r.text, re.S)
    assert linha
    celulas = re.findall(r"<td [^>]*>(.*?)</td>", linha.group(1), re.S)
    assert celulas == ["33,3%", "1h30", "—", "0,6"]
    assert f'aria-label="{format_day("pt-BR", segunda)}: 1h30"' in r.text  # a semana

    # O CSV: as porcentagens e as tarefas por dia em número; as horas por chamado em horas e min.
    r = client.get("/relatorios/csv", params={**semana, "bloco": "1"})
    linhas = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
    assert linhas[0] == [
        "Pessoa",
        "Hora extra (%)",
        "Horas por chamado",
        "Horas por chamado (min)",
        "Taxa de conclusão (%)",
        "Tarefas por dia útil",
    ]
    assert linhas[1] == ["Ana", "33,3", "1,50", "90", "", "0,6"]

    # Hoje, com os dois chamados registrados e nenhum concluído: 0%.
    hoje = datetime.now(TIMEZONE).date()
    r = client.get("/relatorios/blocos", params=_um_dia(hoje, aba=modelo))
    assert re.search(r"<dt[^>]*>Taxa de conclusão</dt>\s*<dd[^>]*>0%</dd>", r.text)
    assert "Acima de 100%" not in r.text
    # Concluídos os dois, e um deles registrado antes: 2 de 1, com o aviso.
    for numero in (um, dois):
        r = client.post(
            f"{API}/{numero}/transitions",
            json={"action": "close", "comment": "Pronto", "resolution_code_id": 1},
        )
        assert r.status_code == 200, r.text
    db.execute(update(Ticket).where(Ticket.number == um).values(created_at=em(segunda, 9)))
    db.commit()
    r = client.get("/relatorios/blocos", params=_um_dia(hoje, aba=modelo))
    assert re.search(r"<dt[^>]*>Taxa de conclusão</dt>\s*<dd[^>]*>200%</dd>", r.text)
    assert "Acima de 100%: concluiu mais do que registrou." in r.text


def test_media_dos_tempos_no_editor_e_na_tela(client: TestClient, cenario: dict[str, Any]) -> None:
    # A escolha só aparece com um tempo até a conclusão; sem ele, volta à mediana.
    dados = formulario(
        client,
        nome="Tempos",
        horas="hm",
        blocos="2",
        acao="atualizar",
        **{
            "b0-visual": "cards",
            "b0-medidas": ["lead_time", "closed"],
            "b0-agregacao": "mean",
            "b1-visual": "cards",
            "b1-medidas": ["hours"],
            "b1-agregacao": "mean",
        },
    )
    r = client.post("/relatorios/modelos", data=dados)
    assert '<option value="mean" selected>Média</option>' in r.text
    assert 'name="b1-agregacao"' not in r.text
    assert '<dt class="text-muted">Média até a conclusão</dt>' in r.text
    # O número abre a lista dos concluídos, com o nome da média.
    listas = re.findall(r'href="(/relatorios/chamados\?[^"]+medida=lead_time[^"]*)"', r.text)
    assert listas and all("agregacao=media" in u for u in listas)
    html = client.get(listas[0].replace("&amp;", "&")).text
    assert "Média até a conclusão" in html

    modelo = _criar(
        client,
        "Tempos",
        **{
            "b0-visual": "table",
            "b0-agrupar": "team",
            "b0-medidas": ["lead_time"],
            "b0-agregacao": "mean",
        },
    )
    r = client.get("/relatorios/blocos", params={"aba": modelo})
    assert ">Média até a conclusão</th>" in r.text
    r = client.get("/relatorios/csv", params={"aba": modelo, "bloco": "0"})
    cabecalho = r.content.decode("utf-8-sig").splitlines()[0]
    assert cabecalho == "Grupo;Média até a conclusão;Média até a conclusão (min)"


def test_mapa_de_calor(client: TestClient, cenario: dict[str, Any]) -> None:
    segunda = dia_util_passado()
    numero = registrar(client, cenario)["number"]
    tarefa(client, numero, 60, em(segunda, 10))
    tarefa(client, numero, 15, em(segunda + timedelta(days=7), 10, 30))
    tarefa(client, numero, 20, em(segunda + timedelta(days=1), 15))
    modelo = _criar(
        client,
        "Calor",
        **{"b0-visual": "heatmap", "b0-agrupar": "weekday_hour", "b0-medida": "hours"},
    )
    filtros = {
        "aba": modelo,
        "periodo": "personalizado",
        "de": segunda.isoformat(),
        "ate": (segunda + timedelta(days=7)).isoformat(),
    }
    r = client.get("/relatorios/blocos", params=filtros)
    assert "Horas por dia da semana e hora" in r.text

    # O maior valor no tom mais forte; os outros pelo primeiro limite que não passam (os limites
    # são quintos de 1h15: 15min, 30min…); sem nada, a célula vazia, só com a borda.
    def celula(texto: str) -> str:
        achado = re.search(
            rf'<span class="group relative h-6 rounded-sm ([^"]+)">\s*<span[^>]*><strong[^>]*>'
            rf"[^<]*</strong><span[^>]*> · {re.escape(texto)}</span>",
            r.text,
        )
        assert achado, texto
        return achado.group(1)

    assert celula("Segunda-feira, 10h") == "bg-heat-5"
    assert celula("Terça-feira, 15h") == "bg-heat-2"  # 20 min: até 30min
    assert celula("Domingo, 0h") == "border border-border"
    assert "até 15min</li>" in r.text and "até 1h15</li>" in r.text and ">Nada</li>" in r.text
    # O leitor de tela lê a tabela; a grade fica escondida dele.
    assert '<table class="sr-only">' in r.text and '<th scope="row">Domingo</th>' in r.text
    assert 'gap-0.5 text-xs text-muted" aria-hidden="true">' in r.text

    # Poucos valores (no máximo 2 tarefas na hora): só os limites que existem, sem repetir, e a
    # cor de cada célula é a do limite dela.
    tarefas = _criar(
        client,
        "Calor de tarefas",
        **{"b0-visual": "heatmap", "b0-agrupar": "weekday_hour", "b0-medida": "tasks"},
    )
    r = client.get("/relatorios/blocos", params={**filtros, "aba": tarefas})
    assert re.findall(r"(até \d+)</li>", r.text) == ["até 1", "até 2"]
    assert celula("Terça-feira, 15h") == "bg-heat-1"  # 1 tarefa
    assert celula("Segunda-feira, 10h") == "bg-heat-3"  # 2 tarefas: o tom do limite "até 2"

    # No editor, o mapa só agrupa por dia da semana e hora.
    r = client.get(f"/relatorios/modelos/{modelo}/editar")
    agrupar = re.search(r'name="b0-agrupar".*?</select>', r.text, re.S)
    assert agrupar and agrupar.group(0).count("<option") == 1

    # O CSV: uma linha por dia e hora; o PDF desenha o mapa com a escala da paleta.
    r = client.get("/relatorios/csv", params={**filtros, "bloco": "0"})
    linhas = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
    assert linhas[0][0] == "Dia da semana e hora" and len(linhas) == 170
    assert linhas[11] == ["segunda 10:00", "1,25", "75"]
    pdf = client.get("/relatorios/pdf", params=filtros)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_area_e_linha_de_referencia(client: TestClient, cenario: dict[str, Any]) -> None:
    segunda = dia_util_passado()
    numero = registrar(client, cenario)["number"]
    tarefa(client, numero, 60, em(segunda, 10))
    tarefa(client, numero, 30, em(segunda + timedelta(days=1), 10))
    modelo = _criar(
        client,
        "Referência",
        blocos="2",
        **{
            "b0-visual": "line",
            "b0-agrupar": "day",
            "b0-medida": "hours",
            "b0-area": "1",
            "b0-referencia": "mean",
            "b1-visual": "columns",
            "b1-agrupar": "day",
            "b1-medida": "hours",
            "b1-referencia": "median",
        },
    )
    filtros = {
        "aba": modelo,
        "periodo": "personalizado",
        "de": segunda.isoformat(),
        "ate": (segunda + timedelta(days=2)).isoformat(),
    }
    r = client.get("/relatorios/blocos", params=filtros)
    # A média de 60, 30 e 0 é 30 min; a mediana, também. A linha é tracejada, com o nome.
    assert r.text.count('stroke-dasharray="6 4"') == 4  # as duas linhas e os dois nomes
    assert "Média: 30min</p>" in r.text and "Mediana: 30min</p>" in r.text
    # Nas colunas, a referência vem depois delas (por cima), como no PDF.
    assert re.search(
        r'</ul>\s*<svg class="pointer-events-none[^>]*>\s*<line[^>]*stroke-dasharray="6 4"', r.text
    )
    assert 'class="fill-chart-1" fill-opacity="0.15"' in r.text  # a área, só na linha
    assert r.text.count('fill-opacity="0.15"') == 1
    assert client.get("/relatorios/pdf", params=filtros).content.startswith(b"%PDF")

    # No editor: a referência nas colunas e na linha; a área, só na linha.
    r = client.get(f"/relatorios/modelos/{modelo}/editar")
    assert 'name="b0-area"' in r.text and 'name="b1-area"' not in r.text
    assert 'name="b0-referencia"' in r.text and 'name="b1-referencia"' in r.text
    dados = formulario(
        client,
        nome="X",
        horas="hm",
        blocos="1",
        acao="atualizar",
        **{"b0-visual": "bars", "b0-agrupar": "person", "b0-referencia": "mean", "b0-area": "1"},
    )
    r = client.post("/relatorios/modelos", data=dados)
    assert 'name="b0-referencia"' not in r.text and 'name="b0-area"' not in r.text


def test_barras_e_linha(client: TestClient, cenario: dict[str, Any]) -> None:
    segunda = dia_util_passado()
    numero = registrar(client, cenario)["number"]
    tarefa(client, numero, 90, em(segunda, 19))  # 60 min fora do expediente
    modelo = _criar(
        client,
        "Combo",
        **{
            "b0-visual": "combo",
            "b0-agrupar": "day",
            "b0-medida": "hours",
            "b0-medida2": "overtime",
        },
    )
    filtros = _um_dia(segunda, aba=modelo)
    r = client.get("/relatorios/blocos", params=filtros)
    assert "Horas e horas extras por dia" in r.text
    assert 'class="stroke-chart-2"' in r.text  # a linha da segunda medida
    assert f'aria-label="{format_day("pt-BR", segunda)}: 1h30 · Horas extras: 1h"' in r.text
    assert "Horas extras</li>" in r.text  # a legenda
    assert 'fill-chart-2" aria-hidden="true"><circle' in r.text  # o ponto da linha (um dia só)
    assert re.search(r'<a href="/relatorios\?[^"]*periodo=personalizado[^"]*" hx-boost', r.text)
    assert client.get("/relatorios/pdf", params=filtros).content.startswith(b"%PDF")
    linhas = client.get("/relatorios/csv", params={**filtros, "bloco": "0"}).content
    assert "Horas;Horas (min);Horas extras" in linhas.decode("utf-8-sig")

    # No editor: a medida da linha só entre as da mesma unidade das barras.
    r = client.get(f"/relatorios/modelos/{modelo}/editar")
    linha = re.search(r'name="b0-medida2".*?</select>', r.text, re.S)
    assert linha and 'value="overtime" selected' in linha.group(0)
    assert 'value="hours_per_ticket"' in linha.group(0) and 'value="tasks"' not in linha.group(0)
    # Trocar a das barras para uma contagem leva a linha para outra contagem.
    dados = formulario(
        client,
        nome="X",
        horas="hm",
        blocos="1",
        acao="atualizar",
        **{
            "b0-visual": "combo",
            "b0-agrupar": "week",
            "b0-medida": "opened",
            "b0-medida2": "overtime",
        },
    )
    r = client.post("/relatorios/modelos", data=dados)
    linha = re.search(r'name="b0-medida2".*?</select>', r.text, re.S)
    assert linha and 'value="tasks" selected' in linha.group(0)


def test_numero_grande(client: TestClient, cenario: dict[str, Any]) -> None:
    segunda = dia_util_passado()
    numero = registrar(client, cenario)["number"]
    tarefa(client, numero, 60, em(segunda, 10))
    tarefa(client, numero, 30, em(segunda + timedelta(days=1), 10))
    tarefa(client, numero, 45, em(segunda - timedelta(days=7), 10))
    modelo = _criar(
        client, "Grande", **{"b0-visual": "cards", "b0-medidas": ["hours"], "b0-grande": "1"}
    )
    semana = {
        "aba": modelo,
        "periodo": "personalizado",
        "de": segunda.isoformat(),
        "ate": (segunda + timedelta(days=6)).isoformat(),
        "comparar": "anterior",
    }
    r = client.get("/relatorios/blocos", params=semana)
    assert '<dd class="mt-1 text-5xl tracking-tight font-semibold">1h30</dd>' in r.text
    assert "+100% · antes: 45min" in r.text  # a variação
    assert "block h-16 w-full" in r.text  # a tendência, mais alta
    assert client.get("/relatorios/pdf", params=semana).content.startswith(b"%PDF")

    # No editor, a opção só aparece com uma medida; com duas, sai.
    r = client.get(f"/relatorios/modelos/{modelo}/editar")
    assert 'name="b0-grande" value="1" checked' in r.text
    dados = formulario(
        client,
        nome="X",
        horas="hm",
        blocos="1",
        acao="atualizar",
        **{"b0-visual": "cards", "b0-medidas": ["hours", "tasks"], "b0-grande": "1"},
    )
    r = client.post("/relatorios/modelos", data=dados)
    assert 'name="b0-grande"' not in r.text and "text-5xl" not in r.text


# --- extensão: ajustes por bloco (docs/14 §14.8.3) -------------------------------------------


def _bloco(html: str, i: int) -> str:
    """O cartão inteiro de um bloco da tela, pelo id."""
    achado = re.search(rf'id="bloco-{i}".*?</(?:section|figure)>', html, re.S)
    assert achado, f"sem o bloco {i}"
    return achado.group(0)


def test_filtro_e_periodo_do_bloco(
    client: TestClient, cenario: dict[str, Any], db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O filtro do bloco só restringe o da tela (a interseção campo a campo; sem nada em comum,
    o bloco avisa e não consulta); o período do bloco é um relativo que as setas não mexem. Os
    dados vêm uma vez por grupo de blocos com o mesmo período e os mesmos filtros."""
    from chamados.modules.reports import service

    dia = dia_util_passado()  # a segunda da semana passada
    tarefa(client, registrar(client, cenario)["number"], 60, em(dia, 10))  # a Ana
    entrar(client, "bia@x.com")  # a supervisora do TI vê as duas
    tarefa(client, registrar(client, cenario)["number"], 30, em(dia, 11))
    ana = cenario["ana"]
    campos = {
        "blocos": "4",
        "b0-visual": "cards",
        "b0-medidas": "hours",
        "b1-visual": "cards",
        "b1-medidas": "hours",
        "b1-pessoa": ana,
        "b2-visual": "cards",
        "b2-medidas": "hours",
        "b2-periodo": "semana-anterior",
        "b2-pessoa": ana,
        "b3-visual": "table",
        "b3-agrupar": "person",
        "b3-medidas": ["hours", "closed"],
        "b3-periodo": "semana-anterior",
        "b3-pessoa": ana,
    }
    modelo = _criar(client, "Por bloco", **campos)
    config = db.scalar(select(ReportModel.config).where(ReportModel.name == "Por bloco"))
    assert config is not None and config["version"] == 2
    assert config["blocks"][1]["filters"]["people"] == [ana]
    assert config["blocks"][2]["period"] == {"kind": "semana-anterior", "days": None}

    facts = service.facts
    chamadas: list[Any] = []

    async def contar(*args: Any, **kwargs: Any) -> Any:
        chamadas.append(args)
        return await facts(*args, **kwargs)

    monkeypatch.setattr(service, "facts", contar)
    r = client.get("/relatorios/blocos", params=_um_dia(dia, aba=modelo))
    # Quatro blocos, três grupos: o da tela, o da Ana e o da semana anterior com a Ana.
    assert len(chamadas) == 3
    assert ">1h30</dd>" in _bloco(r.text, 0)
    assert ">1h</dd>" in _bloco(r.text, 1) and "Pessoa: Ana" in _bloco(r.text, 1)
    assert "Semana anterior · De " in _bloco(r.text, 2) and ">1h</dd>" in _bloco(r.text, 2)
    # O detalhar e a lista de chamados do bloco levam o período e o filtro dele.
    tabela = _bloco(r.text, 3)
    linha = re.search(r'<a href="(/relatorios\?[^"]+)" hx-boost="true"[^>]*>Ana</a>', tabela)
    assert linha
    query = parse_qs(urlsplit(linha.group(1).replace("&amp;", "&")).query)
    assert query["periodo"] == ["semana-anterior"] and query["pessoa"] == [ana]
    assert "de" not in query
    lista = re.search(r'href="(/relatorios/chamados\?[^"]+)"', tabela)
    assert (
        lista and "periodo=semana-anterior" in lista.group(1) and f"pessoa={ana}" in lista.group(1)
    )

    # Hoje só: o bloco com o período da semana anterior continua com ela.
    hoje = datetime.now(TIMEZONE).date()
    r = client.get("/relatorios/blocos", params=_um_dia(hoje, aba=modelo))
    assert ">0min</dd>" in _bloco(r.text, 0) and ">1h</dd>" in _bloco(r.text, 2)

    # A tela com a Bia: o filtro da Ana não tem nada em comum, e o bloco não consulta.
    chamadas.clear()
    r = client.get("/relatorios/blocos", params=_um_dia(dia, aba=modelo, pessoa=cenario["bia"]))
    assert "O filtro deste bloco (Pessoa: Ana) não combina com o da tela." in _bloco(r.text, 1)
    assert len(chamadas) == 1  # só o b0: os outros não consultam
    # As duas na tela: vale a Ana.
    r = client.get(
        "/relatorios/blocos", params=_um_dia(dia, aba=modelo, pessoa=[ana, cenario["bia"]])
    )
    assert ">1h</dd>" in _bloco(r.text, 1)

    # O CSV e o PDF do bloco usam o mesmo filtro e o mesmo período.
    monkeypatch.setattr(service, "facts", facts)
    r = client.get("/relatorios/csv", params=_um_dia(hoje, aba=modelo, bloco="3"))
    linhas = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
    assert linhas[1][:3] == ["Ana", "1,00", "60"]
    pdf = _capturar(monkeypatch, "render_model")
    client.get("/relatorios/pdf", params=_um_dia(dia, aba=modelo, pessoa=cenario["bia"]))
    blocos = pdf[0][2]
    assert blocos[0].subtitle == "" and blocos[1].subtitle == "Pessoa: Ana"
    assert blocos[1].empty == "O filtro deste bloco (Pessoa: Ana) não combina com o da tela."
    assert blocos[2].subtitle == "Semana anterior · Pessoa: Ana"

    # Um grupo que saiu do alcance fica de fora, com o aviso (o bloco mostra o resto).
    config["blocks"][1]["filters"]["teams"] = [cenario["infra"]]
    db.execute(update(ReportModel).where(ReportModel.name == "Por bloco").values(config=config))
    db.commit()
    r = client.get("/relatorios/blocos", params=_um_dia(dia, aba=modelo))
    assert "ficaram de fora: Grupo." in _bloco(r.text, 1) and ">1h</dd>" in _bloco(r.text, 1)


def test_filtro_do_bloco_no_editor(client: TestClient, cenario: dict[str, Any]) -> None:
    """O editor oferece o período e as etiquetas do filtro em cada bloco, e a prévia os usa; um
    filtro fora do alcance da pessoa não se salva."""
    dia = dia_util_passado()
    tarefa(client, registrar(client, cenario)["number"], 60, em(dia, 10))
    campos = {"blocos": "1", "b0-visual": "cards", "b0-medidas": "hours"}
    dados = formulario(client, nome="X", horas="hm", acao="atualizar", **campos)
    datas = {k: v[0] for k, v in _datas(dia, dia).items()}
    r = client.post("/relatorios/modelos", data={**dados, **datas})
    assert '<summary class="cursor-pointer font-medium">Filtro do bloco</summary>' in r.text
    assert 'id="campo-b0-status"' in r.text and 'id="campo-b0-cliente"' in r.text
    assert 'hx-trigger="etiquetas"' in r.text
    assert '<option value="" selected>O da tela</option>' in r.text
    assert '<details class="rounded-md border border-border p-3">' in r.text  # recolhido
    # Um status que não combina: a prévia avisa; os últimos N dias levam os dias.
    aberto = str(status_id(client, "Pendente"))
    fechado = str(status_id(client, "Concluído"))
    r = client.post(
        "/relatorios/modelos",
        data={
            **dados,
            **datas,
            "status": aberto,
            "b0-status": fechado,
            "b0-periodo": "ultimos-n-dias",
            "b0-dias": "²",
        },
    )
    assert "não combina com o da tela" in r.text
    assert '<details class="rounded-md border border-border p-3" open>' in r.text
    assert 'name="b0-dias"' in r.text and 'value="30"' in r.text  # "²" volta ao padrão
    # Um valor fora da lista fechada vira o da tela.
    r = client.post("/relatorios/modelos", data={**dados, **datas, "b0-periodo": "sempre"})
    assert '<option value="" selected>O da tela</option>' in r.text
    # A Ana não supervisiona: um grupo no filtro do bloco não se salva.
    salvar = {**dados, "acao": "salvar", "b0-grupo": cenario["infra"]}
    r = client.post("/relatorios/modelos", data=salvar)
    assert r.status_code == 422 and "Você não tem permissão para esta ação." in r.text
    # Números enormes ou que não são ASCII não derrubam a tela (o int() tem limite de dígitos).
    enorme = "9" * 5000
    r = client.post(
        "/relatorios/modelos",
        data={**dados, "b0-status": enorme, "acao": f"medida-subir-0-{enorme}"},
    )
    assert r.status_code == 200
    r = client.post("/relatorios/modelos", data={**dados, "blocos": "²"})
    assert r.status_code == 200
    assert client.get("/relatorios/blocos", params={"status": enorme}).status_code == 200


def test_largura_e_altura_do_bloco(
    client: TestClient, cenario: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A largura escolhida vale mais que a grade sem buraco (também no esqueleto); a altura muda
    os gráficos de colunas e de linha e o mapa de calor, e o PDF na mesma proporção."""
    # Um gráfico de meia linha fica sozinho; a tabela, na meia linha; um de linha inteira.
    assert wide(["table", "columns"], ["half", "half"]) == [False, False]
    assert wide(["columns", "line", "columns"], [None, None, "half"]) == [False, False, False]
    assert wide(["columns", "line"], ["full"]) == [True, True]
    campos = {
        "blocos": "3",
        "b0-visual": "table",
        "b0-agrupar": "person",
        "b0-medidas": "hours",
        "b0-largura": "half",
        "b1-visual": "columns",
        "b1-agrupar": "day",
        "b1-medida": "hours",
        "b1-altura": "l",
        "b2-visual": "heatmap",
        "b2-medida": "tasks",
        "b2-altura": "s",
        "b2-largura": "full",
    }
    modelo = _criar(client, "Tamanhos", **campos)
    # A tabela de meia linha faz par com as colunas; o mapa, na linha inteira.
    for url in ("/relatorios/blocos", "/relatorios"):
        larguras = _largura(client.get(url, params={"aba": modelo}).text)
        assert larguras == {0: False, 1: False, 2: True}
    dia = dia_util_passado()
    tarefa(client, registrar(client, cenario)["number"], 60, em(dia, 10))
    r = client.get("/relatorios/blocos", params=_um_dia(dia, aba=modelo))
    assert '<div class="relative h-56">' in _bloco(r.text, 1)
    assert 'class="group relative h-4 rounded-sm' in _bloco(r.text, 2)
    # O editor só oferece a altura onde ela vale; trocar o visual volta à média.
    r = client.get(f"/relatorios/modelos/{modelo}/editar")
    assert 'name="b1-altura"' in r.text and 'name="b0-altura"' not in r.text
    assert '<option value="half" selected>Meia linha</option>' in r.text
    dados = formulario(client, nome="X", horas="hm", acao="atualizar", **campos)
    r = client.post(
        "/relatorios/modelos", data={**dados, "b1-visual": "bars", "b1-agrupar": "person"}
    )
    assert 'name="b1-altura"' not in r.text
    pdf = _capturar(monkeypatch, "render_model")
    client.get("/relatorios/pdf", params=_um_dia(dia, aba=modelo))
    blocos = pdf[0][2]
    assert blocos[1].scale == 1.4 and blocos[2].scale == 0.7


def test_cor_da_serie_do_bloco(
    client: TestClient, cenario: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Barras, colunas e linha escolhem a cor entre as séries da paleta (o nome do token); a
    série de antes continua a `chart-before`, e o PDF usa a mesma cor."""
    campos = {
        "blocos": "2",
        "b0-visual": "line",
        "b0-agrupar": "day",
        "b0-medida": "hours",
        "b0-cor": "chart-3",
        "b0-area": "1",
        "b1-visual": "table",
        "b1-agrupar": "person",
        "b1-medidas": "hours",
        "b1-cor": "chart-4",  # a tabela não tem cor: fica sem
    }
    modelo = _criar(client, "Cores", **campos)
    dia = dia_util_passado()
    tarefa(client, registrar(client, cenario)["number"], 60, em(dia, 10))
    r = client.get("/relatorios/blocos", params=_um_dia(dia, aba=modelo, comparar="anterior"))
    linha = _bloco(r.text, 0)
    assert 'class="stroke-chart-3"' in linha and 'class="fill-chart-3" fill-opacity="0.15"' in linha
    assert "stroke-chart-1" not in linha and "stroke-chart-before" in linha
    assert '<span class="size-3 rounded-sm bg-chart-3"' in linha  # a legenda da comparação
    r = client.get(f"/relatorios/modelos/{modelo}/editar")
    assert '<option value="chart-3" selected>Terceira cor dos gráficos</option>' in r.text
    assert 'name="b1-cor"' not in r.text
    pdf = _capturar(monkeypatch, "render_model")
    client.get("/relatorios/pdf", params=_um_dia(dia, aba=modelo))
    assert pdf[0][2][0].color == "chart-3"
    # Um valor fora da lista fechada vira a cor da instalação.
    dados = formulario(client, nome="X", horas="hm", acao="atualizar", **campos)
    r = client.post("/relatorios/modelos", data={**dados, "b0-cor": "red"})
    assert '<option value="" selected>A da instalação</option>' in r.text


def test_formato_das_horas_e_casas_do_bloco(client: TestClient, cenario: dict[str, Any]) -> None:
    """O bloco troca o formato das horas do modelo e escolhe as casas das horas em decimal, das
    porcentagens e das taxas; os eixos seguem o formato. O CSV continua com as horas em decimal e
    em minutos, mas usa as casas nas porcentagens."""
    dia = dia_util_passado()
    numero = registrar(client, cenario)["number"]
    tarefa(client, numero, 60, em(dia, 19))  # fora do expediente
    tarefa(client, numero, 30, em(dia, 10))
    campos = {
        "blocos": "3",
        "b0-visual": "cards",
        "b0-medidas": ["hours", "overtime_rate"],
        "b0-horas": "decimal",
        "b0-casas": "2",
        "b1-visual": "columns",
        "b1-agrupar": "day",
        "b1-medida": "hours",
        "b1-horas": "decimal",
        "b1-casas": "0",
        "b2-visual": "table",
        "b2-agrupar": "person",
        "b2-medidas": ["overtime_rate"],
        "b2-casas": "0",
    }
    modelo = _criar(client, "Formatos", **campos)  # o modelo em hh:mm
    r = client.get("/relatorios/blocos", params=_um_dia(dia, aba=modelo))
    cartoes = _bloco(r.text, 0)
    assert ">1,50 h</dd>" in cartoes and ">66,67%</dd>" in cartoes
    assert ">2 h</span>" in _bloco(r.text, 1)  # a marca do eixo, sem casas
    assert ">67%</td>" in _bloco(r.text, 2)
    r = client.get("/relatorios/csv", params=_um_dia(dia, aba=modelo, bloco="0"))
    linhas = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
    assert linhas[1] == ["1,50", "90", "66,67"]
    # O editor só oferece o formato das horas onde há horas; as casas, também nas porcentagens.
    r = client.get(f"/relatorios/modelos/{modelo}/editar")
    assert '<option value="decimal" selected>Decimal (7,5 h)</option>' in r.text
    assert 'name="b2-horas"' not in r.text and 'name="b2-casas"' in r.text


def test_esconder_outros(client: TestClient, cenario: dict[str, Any], db: Session) -> None:
    """Com só os maiores, a linha "Outros" pode sumir; o total continua o do período inteiro, e o
    rodapé (também no CSV e no PDF) diz isso. Nos agrupamentos fixos não há só os maiores."""
    dia = dia_util_passado()
    padaria = criar_cliente(db, "Padaria", "11222333000181")
    tarefa(client, registrar(client, cenario, client_id=padaria)["number"], 60, em(dia, 10))
    tarefa(client, registrar(client, cenario)["number"], 30, em(dia, 11))
    campos = {
        "blocos": "1",
        "b0-visual": "table",
        "b0-agrupar": "client",
        "b0-medidas": "hours",
        "b0-maiores": "1",
        "b0-semOutros": "1",
    }
    modelo = _criar(client, "Sem outros", **campos)
    r = client.get("/relatorios/blocos", params=_um_dia(dia, aba=modelo))
    tabela = _bloco(r.text, 0)
    assert "Padaria" in tabela and "Outros" not in tabela and "Sem cliente" not in tabela
    assert "Total do período, com todos</th>" in tabela and ">1h30</a>" not in tabela
    assert re.search(r"<td[^>]*>1h30</td>", tabela)  # o total, com o sem cliente
    r = client.get("/relatorios/csv", params=_um_dia(dia, aba=modelo, bloco="0"))
    linhas = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
    assert linhas[-1] == ["Total do período, com todos", "1,50", "90"] and len(linhas) == 3
    r = client.get(f"/relatorios/modelos/{modelo}/editar")
    assert 'id="campo-b0-semOutros"' in r.text and "checked" in r.text
    # Por dia: nem só os maiores, nem esconder (mesmo que o formulário mande).
    dados = formulario(client, nome="X", horas="hm", acao="atualizar", **campos)
    r = client.post("/relatorios/modelos", data={**dados, "b0-agrupar": "day"})
    assert 'name="b0-maiores"' not in r.text and 'name="b0-semOutros"' not in r.text


def test_colunas_da_lista_e_ordem_das_medidas(
    client: TestClient, cenario: dict[str, Any], db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lista de tarefas mostra as colunas escolhidas (na ordem fixa), também no CSV e no PDF;
    a tabela, as medidas na ordem guardada, que as setas do editor mudam."""
    dia = dia_util_passado()
    padaria = criar_cliente(db, "Padaria", "11222333000181")
    numero = registrar(client, cenario, client_id=padaria)["number"]
    tarefa(client, numero, 60, em(dia, 10))
    campos = {
        "blocos": "2",
        "b0-visual": "tasks",
        "b0-colunas": ["status", "ticket", "client", "when"],
        "b1-visual": "table",
        "b1-agrupar": "person",
        "b1-medidas": ["hours", "tasks"],
        "b1-sequencia": ["tasks", "hours"],
    }
    modelo = _criar(client, "Colunas", **campos)
    config = db.scalar(select(ReportModel.config).where(ReportModel.name == "Colunas"))
    assert config is not None
    assert config["blocks"][0]["columns"] == ["when", "ticket", "client", "status"]
    assert config["blocks"][1]["measures"] == ["tasks", "hours"]
    r = client.get("/relatorios/blocos", params=_um_dia(dia, aba=modelo))
    lista = _bloco(r.text, 0)
    cabecalho = re.findall(r'<th scope="col"[^>]*>([^<]+)</th>', lista)
    assert cabecalho == ["Quando", "Chamado", "Cliente", "Status"]
    assert '<td class="px-3 py-2">Padaria</td>' in lista and "Pessoa" not in lista
    tabela = re.findall(r'<th scope="col"[^>]*>([^<]+)</th>', _bloco(r.text, 1))
    assert tabela == ["Pessoa", "Tarefas", "Horas"]
    r = client.get("/relatorios/csv", params=_um_dia(dia, aba=modelo, bloco="0"))
    linhas = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
    assert linhas[0] == ["Quando", "Chamado", "Título", "Cliente", "Status", "Expediente"]
    assert linhas[1][1:4] == [str(numero), "Impressora não imprime", "Padaria"]
    r = client.get("/relatorios/csv", params=_um_dia(dia, aba=modelo, bloco="1"))
    linhas = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
    assert linhas[0] == ["Pessoa", "Tarefas", "Horas", "Horas (min)"]
    pdf = _capturar(monkeypatch, "render_model")
    client.get("/relatorios/pdf", params=_um_dia(dia, aba=modelo))
    lista_pdf, tabela_pdf = pdf[0][2]
    assert lista_pdf.columns == ["Quando", "Chamado", "Cliente", "Status"]
    assert lista_pdf.rows[0][1:3] == [f"#{numero} Impressora não imprime", "Padaria"]
    assert tabela_pdf.columns == ["Pessoa", "Tarefas", "Horas"]

    # No editor: as setas trocam as medidas de lugar; uma marcada agora entra no fim.
    dados = formulario(client, nome="X", horas="hm", **campos)
    r = client.post("/relatorios/modelos", data={**dados, "acao": "medida-subir-1-1"})
    assert re.findall(r'name="b1-sequencia" value="(\w+)"', r.text) == ["hours", "tasks"]
    marcadas = {"b1-medidas": ["hours", "tasks", "overtime"]}
    r = client.post("/relatorios/modelos", data={**dados, "acao": "atualizar", **marcadas})
    ordem = re.findall(r'name="b1-sequencia" value="(\w+)"', r.text)
    assert ordem == ["tasks", "hours", "overtime"]
    assert 'aria-label="Descer Tarefas"' in r.text
    # Sem escolha, as colunas de sempre marcadas.
    sem = {k: v for k, v in dados.items() if k != "b0-colunas"}
    r = client.post("/relatorios/modelos", data={**sem, "acao": "atualizar"})
    assert 'id="campo-b0-colunas-person" name="b0-colunas" value="person" checked' in r.text
    assert 'id="campo-b0-colunas-client" name="b0-colunas" value="client" class' in r.text


# --- organizar abas (docs/14 §14.8.1) --------------------------------------------------------


def _abas(html: str) -> list[str]:
    """Os nomes das abas dos modelos na barra, na ordem (sem o Histórico, que é fixo)."""
    barra = re.search(r'<nav aria-label="Modelos de relatório".*?</nav>', html, re.S)
    assert barra, "sem a barra de abas"
    return [a for a in re.findall(r">([^<>]+)</a>", barra.group(0)) if a != "Histórico"]


def _organizar(
    client: TestClient, ordem: list[str], mostrar: list[str], acao: str = "salvar", **campos: Any
) -> Any:
    dados = formulario(client, ordem=ordem, mostrar=mostrar, acao=acao, **campos)
    return client.post("/relatorios/abas", data=dados, follow_redirects=False)


PRONTOS = ["produtividade", "clientes", "horas-extras", "chamados"]


def test_organizar_abas(client: TestClient, cenario: dict[str, Any]) -> None:
    alfa, beta = _criar(client, "Alfa"), _criar(client, "Beta")
    r = client.get("/relatorios/blocos")
    # Sem preferência: os prontos e os da pessoa pelo nome; o item no menu Modelo abre o diálogo.
    assert _abas(r.text) == [
        "Produtividade",
        "Clientes",
        "Horas extras",
        "Chamados",
        "Alfa",
        "Beta",
    ]
    assert 'data-abre-dialogo="organizar-abas"' in r.text
    # O inicial (sem modelo inicial, a primeira aba) não se esconde.
    assert 'name="mostrar" value="produtividade" checked disabled' in r.text

    # Beta primeiro; Clientes e Chamados escondidos. Volta à aba e aos filtros, com o aviso.
    ordem = [beta, *PRONTOS, alfa]
    r = _organizar(
        client,
        ordem,
        [beta, "produtividade", "horas-extras", alfa],
        aba="clientes",
        periodo="mes-anterior",
    )
    assert r.status_code == 303
    volta = parse_qs(urlsplit(r.headers["location"]).query)
    assert volta == {"aba": ["clientes"], "periodo": ["mes-anterior"]}
    r = client.get("/relatorios/blocos")
    assert "Abas salvas." in r.text
    # Sem aba, a inicial passa a ser a primeira da ordem.
    assert 'aria-current="page">Beta</a>' in r.text
    assert _abas(r.text) == ["Beta", "Produtividade", "Horas extras", "Alfa"]
    assert "data-abre-ao-carregar" not in r.text

    # A escondida abre pelo link e aparece no lugar dela enquanto está aberta.
    r = client.get("/relatorios/blocos", params={"aba": "chamados"})
    assert 'aria-current="page">Chamados</a>' in r.text
    assert _abas(r.text) == ["Beta", "Produtividade", "Horas extras", "Chamados", "Alfa"]

    # A seta grava a ordem na hora e o diálogo volta aberto. O Mostrar do inicial (Beta) vem
    # desativado e não é enviado: ao descer, ele continua aparecendo.
    r = _organizar(client, ordem, ["produtividade", alfa], aba=beta, acao="descer-0")
    volta = parse_qs(urlsplit(r.headers["location"]).query)
    assert volta == {"aba": [beta], "organizar": ["1"]}
    r = client.get(r.headers["location"])
    assert 'id="organizar-abas" data-abre-ao-carregar' in r.text
    assert _abas(r.text) == ["Produtividade", "Beta", "Alfa"]

    # Um modelo novo entra no fim; um apagado sai da ordem.
    gama = _criar(client, "Gama")
    client.post(f"/relatorios/modelos/{alfa}/excluir", data=formulario(client))
    assert _abas(client.get("/relatorios/blocos").text) == ["Produtividade", "Beta", "Gama"]

    # Um id que não é aba da pessoa responde como os modelos de outra: 404.
    assert _organizar(client, [*PRONTOS, str(uuid.uuid4())], PRONTOS).status_code == 404
    assert _organizar(client, PRONTOS, ["nada"]).status_code == 404
    assert _organizar(client, [beta, gama], [beta]).status_code == 303


def test_modelo_inicial_nao_fica_escondido(client: TestClient, cenario: dict[str, Any]) -> None:
    alfa = _criar(client, "Alfa")
    beta = _criar(client, "Beta", inicial="1")
    # Esconder o inicial não vale: ele continua na barra, com o Mostrar marcado e travado.
    _organizar(client, [*PRONTOS, alfa, beta], PRONTOS)
    r = client.get("/relatorios/blocos")
    assert 'aria-current="page">Beta</a>' in r.text
    assert _abas(r.text) == [*["Produtividade", "Clientes", "Horas extras", "Chamados"], "Beta"]
    assert f'name="mostrar" value="{beta}" checked disabled' in r.text
    # Marcar como inicial um modelo escondido o faz aparecer de novo.
    dados = formulario(client, nome="Alfa", horas="hm", blocos="1", acao="salvar", inicial="1")
    r = client.post(f"/relatorios/modelos/{alfa}", data={**dados, **TABELA}, follow_redirects=False)
    assert r.status_code == 303
    r = client.get("/relatorios/blocos")
    assert 'aria-current="page">Alfa</a>' in r.text
    # O Beta não ficou guardado como escondido: era o inicial quando a ordem foi salva.
    assert _abas(r.text)[-2:] == ["Alfa", "Beta"]


def test_abas_de_cada_pessoa(client: TestClient, cenario: dict[str, Any]) -> None:
    """A preferência é da pessoa: a de uma não muda a da outra, e o modelo de outra é 404."""
    alfa = _criar(client, "Alfa")
    _organizar(client, ["chamados", alfa, *PRONTOS[:3]], ["chamados", alfa])
    assert _abas(client.get("/relatorios/blocos").text) == ["Chamados", "Alfa"]
    entrar(client, "bia@x.com")
    r = client.get("/relatorios/blocos")
    assert _abas(r.text) == ["Produtividade", "Clientes", "Horas extras", "Chamados"]
    assert _organizar(client, [*PRONTOS, alfa], PRONTOS).status_code == 404
    _organizar(client, PRONTOS[::-1], PRONTOS)
    assert _abas(client.get("/relatorios/blocos").text) == [
        "Chamados", "Horas extras", "Clientes", "Produtividade"
    ]  # fmt: skip
    entrar(client, "ana@x.com")
    assert _abas(client.get("/relatorios/blocos").text) == ["Chamados", "Alfa"]


def test_descricao_do_modelo(
    client: TestClient, cenario: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Os prontos têm a descrição do catálogo, na dica da aba (e no PDF); abaixo dela, não.
    r = client.get("/relatorios/blocos", params={"aba": "clientes"})
    descricao = "Horas e chamados registrados e concluídos de cada cliente."
    assert f'title="{descricao}"' in r.text and f">{descricao}</p>" not in r.text

    # A do modelo da pessoa: texto livre (escapado), até 200 caracteres, editada no editor.
    modelo = _criar(client, "Com descrição", descricao="  Horas & <b>chamados</b>  ")
    r = client.get(f"/relatorios/modelos/{modelo}/editar")
    assert 'name="descricao" type="text" value="Horas &amp; &lt;b&gt;chamados&lt;/b&gt;"' in r.text
    r = client.get("/relatorios/blocos", params={"aba": modelo})
    escapada = "Horas &amp; &lt;b&gt;chamados&lt;/b&gt;"
    assert f'title="{escapada}"' in r.text and f">{escapada}</p>" not in r.text
    longo = _criar(client, "Longo", descricao="x" * 300)
    assert "x" * 200 + '"' in client.get(f"/relatorios/modelos/{longo}/editar").text

    # No PDF, abaixo do título.
    chamadas = _capturar(monkeypatch, "render_model")
    r = client.get(_link_pdf(client.get("/relatorios/blocos", params={"aba": modelo}).text))
    assert r.status_code == 200
    assert chamadas[0][1][0] == "Horas & <b>chamados</b>"


def test_pdf_configuravel(
    client: TestClient, cenario: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A orientação, o título e o rodapé do PDF, e o bloco fora do PDF (que fica na tela)."""
    dia = dia_util_passado()
    numero = registrar(client, cenario)["number"]
    tarefa(client, numero, 90, em(dia, 19))
    campos = {
        "b0-visual": "cards",
        "b0-medidas": ["hours"],
        "b1-visual": "bars",
        "b1-agrupar": "person",
        "b1-medida": "overtime",
        "b1-foraDoPdf": "1",
        "pdf-orientacao": "landscape",
        "pdf-titulo": "Horas do mês",
        "pdf-rodape": "Uso interno",
    }
    dados = formulario(client, nome="Mensal", horas="hm", blocos="2", acao="salvar", **campos)
    r = client.post("/relatorios/modelos", data=dados, follow_redirects=False)
    modelo = parse_qs(urlsplit(r.headers["location"]).query)["aba"][0]
    # O editor guarda as escolhas.
    r = client.get(f"/relatorios/modelos/{modelo}/editar")
    assert '<option value="landscape" selected>Paisagem (A4 deitado)</option>' in r.text
    assert 'name="pdf-titulo" type="text" value="Horas do mês"' in r.text
    assert 'name="pdf-rodape" type="text" value="Uso interno"' in r.text
    assert 'name="b1-foraDoPdf" value="1" checked' in r.text
    assert 'name="b0-foraDoPdf" value="1" class' in r.text  # o outro continua no PDF

    # Na tela, os dois blocos.
    r = client.get("/relatorios/blocos", params=_um_dia(dia, aba=modelo))
    assert 'id="bloco-1"' in r.text
    assert client.get(_link_pdf(r.text)).content.startswith(b"%PDF-1")  # desenhado de verdade
    chamadas = _capturar(monkeypatch, "render_model")
    client.get(_link_pdf(r.text))
    titulo, linhas, blocos, pagina, _, _ = chamadas[0]
    assert titulo == "Horas do mês"
    assert [type(b).__name__ for b in blocos] == ["Cards"]
    assert (pagina.footer, pagina.landscape) == ("Uso interno", True)
    # O bloco que usa a hora extra ficou fora: o PDF não traz o expediente.
    assert not any(linha.startswith("Hora extra é") for linha in linhas)

    # Os prontos de horas usam o PDF do modelo, com os blocos de cada um e o expediente.
    r = client.get("/relatorios/blocos", params=_um_dia(dia, aba="horas-extras"))
    client.get(_link_pdf(r.text))
    titulo, linhas, blocos, pagina, _, _ = chamadas[1]
    assert titulo == "Horas extras"
    assert (
        linhas[0]
        == "O tempo de tarefa fora do expediente, por dia e por pessoa, e as tarefas que o tiveram."
    )
    assert linhas[-1].startswith(
        "Hora extra é o tempo de tarefa fora do expediente: o da instalação (seg–sex"
    )
    assert [type(b).__name__ for b in blocos] == ["Cards", "Chart", "Chart", "Grid"]
    assert blocos[3].rows[0][2] == f"#{numero} Impressora não imprime"


def test_textos_e_colunas_do_relatorio_para_o_cliente(
    client: TestClient, cenario: dict[str, Any], db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A abertura e as observações (texto livre, escapado), as colunas escolhidas e as horas
    escondidas: na prévia A4 e no PDF, na mesma ordem. Nada de organização interna."""
    padaria = criar_cliente(db, "Padaria Pão Quente", "11222333000181")
    dia = dia_util_passado()
    numero = registrar(client, cenario, client_id=padaria, title="Impressora")["number"]
    tarefa(client, numero, 90, em(dia, 19))
    modelo = _criar(
        client,
        "Para a padaria",
        publico="client",
        **{
            "cliente-abertura": "Prezados,\r\nsegue o resumo & <b>obrigado</b>.",
            "cliente-observacoes": "Dúvidas: suporte@x.com",
            "cliente-colunas": ["ticket", "status", "nada"],
            "cliente-semHoras": "1",
        },
    )
    # O editor guarda as escolhas.
    r = client.get(f"/relatorios/modelos/{modelo}/editar")
    assert ">Prezados,\nsegue o resumo &amp; &lt;b&gt;obrigado&lt;/b&gt;.</textarea>" in r.text
    assert 'name="cliente-colunas" value="ticket" checked' in r.text
    assert 'name="cliente-colunas" value="title" class' in r.text
    assert 'name="cliente-semHoras" value="1" checked' in r.text

    # A prévia: abertura, totais sem as horas, só as colunas escolhidas, observações.
    filtros = _um_dia(dia, aba=modelo, cliente=padaria)
    r = client.get("/relatorios/blocos", params=filtros)
    folha = _folha(r.text)
    abertura = "Prezados,\nsegue o resumo &amp; &lt;b&gt;obrigado&lt;/b&gt;."
    assert f'<p class="mt-[1.2em] whitespace-pre-line">{abertura}</p>' in folha
    assert folha.index(abertura) < folha.index("<dl") < folha.index("<table")
    assert folha.index("<table") < folha.index("Dúvidas: suporte@x.com")
    assert "grid-cols-2" in folha and ">Horas</dt>" not in folha
    cabecalho = re.findall(r'<th scope="col"[^>]*>([^<]+)</th>', folha)
    assert cabecalho == ["Chamado", "Status"]
    assert "Impressora" not in folha  # sem a coluna do título

    chamadas = _capturar(monkeypatch, "render_client")
    client.get(_link_pdf(r.text))
    _, _, _, abertura, totais, chamados, observacoes, _ = chamadas[0]
    assert abertura == "Prezados,\nsegue o resumo & <b>obrigado</b>."
    assert observacoes == "Dúvidas: suporte@x.com"
    assert [rotulo for rotulo, _ in totais] == ["Chamados registrados", "Chamados concluídos"]
    assert chamados.columns == ["Chamado", "Status"]
    assert chamados.rows[0][0] == f"#{numero}" and len(chamados.rows[0]) == 2


def test_expediente_usado_so_de_quem_a_pessoa_ve(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O "Expediente usado" (no PDF) cita os expedientes próprios e de grupo que valeram no
    período, só das pessoas e dos grupos ao alcance de quem vê (docs/14 §14.7)."""
    ana = criar_usuario(db, "ana@x.com", nome="Ana", grupos={"TI": "member"})
    criar_usuario(db, "bia@x.com", nome="Bia", grupos={"TI": "supervisor"})
    caio = criar_usuario(db, "caio@x.com", nome="Caio", grupos={"Infra": "member"})
    criar_usuario(db, "admin@x.com", "admin", nome="Admin")
    ti = db.scalar(select(Team).where(Team.name == "TI"))
    assert ti is not None
    todos = [0, 1, 2, 3, 4, 5, 6]
    db.add_all(
        [
            WorkSchedule(team_id=ti.id, weekdays=todos[:5], start=time(9), end=time(17)),
            WorkSchedule(user_id=ana.id, weekdays=todos, start=time(6), end=time(12)),
            WorkSchedule(user_id=caio.id, weekdays=todos[:6], start=time(7), end=time(16)),
        ]
    )
    db.commit()
    dia = dia_util_passado()
    inicio = "Hora extra é o tempo de tarefa fora do expediente: o da instalação (seg–sex"
    esperado = {
        # A supervisora do TI: ela segue o do grupo; a Ana tem o próprio; o Caio fica de fora.
        "bia@x.com": " 08:00–18:00), o do grupo TI (1 pessoa) e o próprio de Ana, sem",
        "ana@x.com": " 08:00–18:00) e o próprio de Ana, sem",
        "admin@x.com": " 08:00–18:00), o do grupo TI (1 pessoa) e o próprio de 2 pessoas"
        " (Ana, Caio), sem",
    }
    chamadas = _capturar(monkeypatch, "render_model")
    for email, texto in esperado.items():
        entrar(client, email)
        r = client.get("/relatorios/blocos", params=_um_dia(dia, aba="horas-extras"))
        assert "Hora extra é o tempo de tarefa" not in r.text, email  # só no PDF
        client.get(_link_pdf(r.text))
        assert (inicio + texto) in chamadas[-1][1][-1], email
