"""Tela dos relatórios no servidor (ADR 0011, docs/14 §14.7 e §14.8).

Cenário (a fixture `cenario`): Ana e Bia (supervisora) no TI, Caio na Infra. O escopo é decidido
pela API (`reports/service.resolve`); a tela repassa os filtros e mostra o erro.
"""

import csv
import io
import re
import uuid
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from chamados.modules.audit.models import AuditLog
from chamados.modules.catalog.models import TicketStatus
from chamados.modules.reports import model_pdf
from chamados.modules.reports.builder import previous_period, relative_period
from chamados.modules.reports.models import ReportModel
from chamados.modules.system.models import SystemSetting
from chamados.modules.tickets.models import Ticket
from chamados.web.formatting import TIMEZONE, format_day, format_month
from chamados.web.reports_blocks import wide
from tests.apoio import API, dia_util_passado, em, formulario, registrar, status_id, tarefa
from tests.conftest import criar_cliente, criar_usuario, entrar, outra_sessao


def _um_dia(dia: date, **extra: str | list[str]) -> dict[str, str | list[str]]:
    return {"periodo": "personalizado", "de": dia.isoformat(), "ate": dia.isoformat(), **extra}


def _pdf(html: str, arquivo: str = "pdf") -> dict[str, list[str]]:
    """Os parâmetros de um link do menu Baixar (o PDF ou um CSV)."""
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
    assert "Chamados registrados" in r.text
    assert 'aria-current="page">Produtividade</a>' in r.text
    pdf = _pdf(r.text)
    assert pdf["start"] == [hoje.replace(day=1).isoformat()]
    assert pdf["locale"] == ["pt-BR"]
    # O menu Baixar: o CSV da tabela da aba e o de todas as tarefas, com os mesmos filtros.
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
    assert "Hora extra é o tempo de tarefa fora do expediente: Seg, Ter, Qua, Qui, Sex" in r.text
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
    # O link leva ao PDF com os mesmos números.
    url = re.search(r'<a href="(/api/v1/reports/pdf\?[^"]+)"', r.text).group(1)  # type: ignore[union-attr]
    resposta = client.get(url.replace("&amp;", "&"))
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
    assert 'name="comparar" value="1" checked' in r.text

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

    # As abas de horas continuam com o PDF da API; a Chamados e os modelos, com o do modelo.
    assert "/relatorios/pdf?" not in client.get("/relatorios/blocos").text
    assert "/relatorios/pdf?" in client.get("/relatorios/blocos", params={"aba": "chamados"}).text
    r = client.get("/relatorios/blocos", params=_um_dia(dia, aba=modelo, comparar="1"))
    assert client.get(_link_pdf(r.text)).content.startswith(b"%PDF-1")  # desenhado de verdade
    chamadas = _capturar(monkeypatch, "render_model")
    r = client.get(_link_pdf(r.text))
    assert r.status_code == 200 and r.content == b"%PDF-teste"
    assert r.headers["content-type"] == "application/pdf"
    titulo, linhas, blocos, rodape, cores = chamadas[0]
    assert titulo == "Mensal" and cores == ("#C2410C", "#1D4ED8", "#D3785C")
    anterior = (dia - timedelta(days=1)).strftime("%d/%m/%Y")
    assert linhas[0] == f"Período: {dia:%d/%m/%Y} a {dia:%d/%m/%Y}"
    assert linhas[1] == f"Comparado com {anterior} a {anterior}"
    assert [type(b).__name__ for b in blocos] == ["Cards", "Chart", "Grid"]
    assert blocos[0].items[0][:2] == ("Horas", "1h30")
    assert blocos[1].kind == "stacked" and blocos[1].points[0][1:3] == (90, 60)
    # Comparando, a tabela tem a variação (sem base: vazia), com uma abreviatura no lugar do Δ.
    assert blocos[2].columns == ["Pessoa", "Horas", "Var."]
    assert blocos[2].rows == [["Ana", "1h30", ""]] and blocos[2].total == ["1h30", ""]
    assert rodape.endswith("por Ana")
    registro = db.scalars(
        select(AuditLog).where(AuditLog.action == "report.exported").order_by(AuditLog.id)
    ).all()[-1]
    assert (registro.after or {})["format"] == "pdf" and (registro.after or {})["table"] == "model"


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
    assert 'name="atendeu"' in r.text and "formato fixo" in r.text
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
    assert "Prévia do relatório para Padaria Pão Quente." in r.text
    assert '<td class="px-3 py-2">#' + str(numero) + "</td>" in r.text
    assert "De outro cliente" not in r.text
    assert '<th scope="col" class="px-3 py-2 font-medium">Atendido por</th>' in r.text
    assert '<th scope="col" class="px-3 py-2 font-medium">Horas extras</th>' not in r.text

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
    logo, titulo, linhas, totais, chamados, rodape = chamadas[0]
    assert logo == b"hello" and titulo == "Relatório de atendimento"
    assert linhas[0] == "Padaria Pão Quente" and linhas[1].startswith("Período:")
    assert totais[0] == ("Horas", "1h30")
    assert chamados.columns[-1] == "Atendido por"
    assert chamados.rows[0][0] == f"#{numero}" and chamados.rows[0][-1] == "Ana"
    assert "Ana" not in rodape  # sem o nome de quem gerou
    sem_cliente = client.get("/relatorios/pdf", params=_um_dia(dia, aba=modelo))
    assert sem_cliente.status_code == 422


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
    r = client.get("/relatorios/blocos", params={"aba": "clientes"})
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
    assert '<input type="checkbox" id="campo-comparar" name="comparar"' in r.text
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
    assert "Prévia do relatório para Padaria Pão Quente." in r.text


def _seta(html: str, qual: str) -> dict[str, list[str]] | None:
    """A query da seta do período ("Período anterior" ou "Próximo período"); None: desativada."""
    achado = re.search(rf'<a href="([^"]+)" hx-boost="true" [^>]*aria-label="{qual}:', html)
    if achado is None:
        assert re.search(rf'aria-disabled="true" [^>]*aria-label="{qual}:', html)
        return None
    return parse_qs(urlsplit(achado.group(1).replace("&amp;", "&")).query)


def _datas(inicio: date, fim: date) -> dict[str, list[str]]:
    return {"periodo": ["personalizado"], "de": [inicio.isoformat()], "ate": [fim.isoformat()]}


def test_setas_do_periodo(client: TestClient, cenario: dict[str, Any]) -> None:
    hoje = datetime.now(TIMEZONE).date()

    def setas(**params: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        html = client.get("/relatorios/blocos", params=params).text
        um, outro = _seta(html, "Período anterior"), _seta(html, "Próximo período")
        sem_aba = [{k: v for k, v in q.items() if k != "aba"} if q else None for q in (um, outro)]
        return sem_aba[0], sem_aba[1]

    # Mês: um mês da lista para cada lado; depois do mês atual, nada.
    inicio, _ = relative_period("mes-anterior", hoje)
    antes, depois = setas(periodo="mes-anterior")
    assert antes == {"periodo": [f"{inicio - timedelta(days=1):%Y-%m}"]}
    assert depois == {"periodo": [f"{hoje:%Y-%m}"]}
    assert setas(periodo="mes-atual")[1] is None

    # Trimestre: os três meses vizinhos, em datas.
    inicio, fim = relative_period("trimestre-anterior", hoje)
    antes, depois = setas(periodo="trimestre-anterior")
    assert antes == _datas(*previous_period(inicio, fim))
    assert depois == _datas(*relative_period("trimestre-atual", hoje))

    # Últimos 30 dias: os 30 de antes; os seguintes ainda não chegaram.
    antes, depois = setas(periodo="ultimos-30-dias")
    assert antes == _datas(hoje - timedelta(days=59), hoje - timedelta(days=30))
    assert depois is None

    # Ano até hoje: as mesmas datas do ano anterior; e, dali, as do seguinte.
    antes, depois = setas(periodo="ano-ate-hoje")
    fim = hoje - timedelta(days=1) if (hoje.month, hoje.day) == (2, 29) else hoje
    assert antes == _datas(date(hoje.year - 1, 1, 1), fim.replace(year=hoje.year - 1))
    assert depois is None
    antes, depois = setas(periodo="personalizado", de="2024-01-01", ate="2024-06-15")
    assert antes == _datas(date(2023, 1, 1), date(2023, 6, 15))
    assert depois == _datas(date(2025, 1, 1), date(2025, 6, 15))
    # Os demais personalizados: o mesmo número de dias.
    antes, depois = setas(periodo="personalizado", de="2025-03-10", ate="2025-03-16")
    assert antes == _datas(date(2025, 3, 3), date(2025, 3, 9))
    assert depois == _datas(date(2025, 3, 17), date(2025, 3, 23))

    # Os filtros continuam; a trilha do detalhar, não.
    html = client.get(
        "/relatorios/blocos",
        params=_um_dia(date(2025, 3, 10), cliente="sem-cliente", origem="mes-atual"),
    ).text
    seta = _seta(html, "Próximo período")
    assert seta and seta["cliente"] == ["sem-cliente"] and "origem" not in seta
    assert seta["de"] == ["2025-03-11"]
    # Período inválido: sem setas.
    html = client.get("/relatorios/blocos", params={"periodo": "personalizado", "de": "x"}).text
    assert "Período anterior" not in html


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
