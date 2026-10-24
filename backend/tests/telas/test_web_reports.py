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
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from chamados.modules.audit.models import AuditLog
from chamados.modules.reports.builder import relative_period
from chamados.modules.reports.models import ReportModel
from chamados.web.formatting import TIMEZONE, format_day, format_month
from tests.apoio import dia_util_passado, em, formulario, registrar, tarefa
from tests.conftest import criar_cliente, entrar


def _um_dia(dia: date, **extra: str | list[str]) -> dict[str, str | list[str]]:
    return {"periodo": "personalizado", "de": dia.isoformat(), "ate": dia.isoformat(), **extra}


def _pdf(html: str, arquivo: str = "pdf") -> dict[str, list[str]]:
    """Os parâmetros de um link do menu Baixar (o PDF ou um CSV)."""
    achado = re.search(rf'<a href="(/api/v1/reports/{arquivo}\?[^"]+)" download', html)
    assert achado, f"sem o link do {arquivo}"
    return parse_qs(urlsplit(achado.group(1).replace("&amp;", "&")).query)


def test_relatorio_do_mes(client: TestClient, cenario: dict[str, Any]) -> None:
    r = client.get("/relatorios")
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
    assert '<option value="">Todos os clientes</option>' in r.text
    assert '<option value="sem-cliente">Sem cliente</option>' in r.text
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

    r = client.get("/relatorios", params=_um_dia(dia))
    assert '<dd class="mt-1 text-2xl font-semibold">2h15</dd>' in r.text
    assert '<dd class="mt-1 text-2xl font-semibold">1h</dd>' in r.text
    # Colunas por dia (com a dica da data e do valor) e barras por pessoa.
    assert f'aria-label="{format_day("pt-BR", dia)}: 2h15"' in r.text
    assert 'height="100.00%"' not in r.text  # o topo do eixo fica acima do maior valor
    assert '<svg width="85.00%" height="16"' in r.text
    assert '<td class="px-3 py-2">Ana</td>' in r.text

    filtros = _um_dia(dia)
    r = client.get("/relatorios", params={**filtros, "aba": "clientes"})
    assert 'aria-current="page">Clientes</a>' in r.text
    assert _pdf(r.text, "csv")["table"] == ["clients"]
    assert "Horas por cliente (os 10 maiores)" in r.text
    assert '<td class="px-3 py-2">Padaria Pão Quente</td>' in r.text
    # As abas levam os filtros junto.
    assert f"de={dia.isoformat()}" in r.text

    r = client.get("/relatorios", params={**filtros, "aba": "horas-extras"})
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
    r = client.get("/relatorios", params=_um_dia(dia, pessoa=cenario["bia"]))
    assert "Você só pode ver os seus próprios números." in r.text
    assert '<button type="button" disabled' in r.text

    entrar(client, "bia@x.com")
    r = client.get("/relatorios", params=_um_dia(dia))
    assert '<option value="">Todas as pessoas</option>' in r.text
    assert f'<option value="{cenario["ana"]}">Ana</option>' in r.text
    assert "Todos os grupos" in r.text  # supervisiona o TI
    r = client.get("/relatorios", params=_um_dia(dia, pessoa=cenario["ana"], grupo=cenario["ti"]))
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
    r = client.get("/relatorios", params=_um_dia(dia, pessoa=[cenario["ana"], cenario["bia"]]))
    assert '<dd class="mt-1 text-2xl font-semibold">30min</dd>' in r.text
    assert _pdf(r.text)["person"] == [cenario["ana"], cenario["bia"]]


def test_filtro_de_cliente(client: TestClient, cenario: dict[str, Any], db: Session) -> None:
    padaria = criar_cliente(db, "Padaria Pão Quente", "11222333000181")
    # Vários clientes e "Sem cliente"; um valor que não é cliente fica de fora.
    r = client.get("/relatorios", params={"cliente": [padaria, "sem-cliente", "xyz"]})
    assert f'<input type="hidden" name="cliente" value="{padaria}">' in r.text
    assert "<span data-rotulo>Padaria Pão Quente</span>" in r.text
    assert '<input type="hidden" name="cliente" value="sem-cliente">' in r.text
    assert "<span data-rotulo>Sem cliente</span>" in r.text
    assert 'value="xyz"' not in r.text and "cliente=xyz&amp;" not in r.text
    pdf = _pdf(r.text)
    assert pdf["client"] == [padaria] and pdf["no_client"] == ["true"]
    # As abas levam os filtros junto.
    assert f"cliente=sem-cliente&amp;cliente={padaria}" in r.text


def test_periodo_personalizado(client: TestClient, cenario: dict[str, Any]) -> None:
    # Ao escolher "Personalizado", as datas começam no primeiro dia do mês e em hoje.
    hoje = datetime.now(TIMEZONE).date()
    r = client.get("/relatorios", params={"periodo": "personalizado"})
    assert (
        f'id="campo-de" name="de" type="date" value="{hoje.replace(day=1).isoformat()}"' in r.text
    )
    assert f'id="campo-ate" name="ate" type="date" value="{hoje.isoformat()}"' in r.text
    assert _pdf(r.text)["end"] == [hoje.isoformat()]
    # As datas não aplicam ao mudar: o botão Aplicar envia.
    assert '<button type="submit"' in r.text and ">Aplicar</button>" in r.text
    assert ">Aplicar</button>" not in client.get("/relatorios").text

    r = client.get(
        "/relatorios", params={"periodo": "personalizado", "de": "2026-10-10", "ate": "2026-10-01"}
    )
    assert "A data final precisa ser igual ou depois da inicial." in r.text
    assert "Chamados registrados" not in r.text
    assert '<button type="button" disabled' in r.text
    r = client.get(
        "/relatorios", params={"periodo": "personalizado", "de": "", "ate": "2026-10-01"}
    )
    assert "A data final precisa ser igual ou depois da inicial." in r.text

    # Mais de 366 dias: o erro vem da API.
    r = client.get(
        "/relatorios", params={"periodo": "personalizado", "de": "2024-01-01", "ate": "2026-01-01"}
    )
    assert "O período pode ter no máximo 366 dias." in r.text

    # Período e aba desconhecidos: o mês atual, na primeira aba.
    r = client.get("/relatorios", params={"periodo": "1999-01", "aba": "xyz"})
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
    r = client.get("/relatorios", params={"periodo": "ultimos-7-dias", "aba": "clientes"})
    assert '<option value="ultimos-7-dias" selected>Últimos 7 dias</option>' in r.text
    inicio = agora - timedelta(days=6)
    assert f"De {format_day('pt-BR', inicio)} a {format_day('pt-BR', agora)}" in r.text
    assert _pdf(r.text, "csv")["start"] == [inicio.isoformat()]
    # As abas mantêm o período relativo (não as datas): o link continua valendo amanhã.
    assert "periodo=ultimos-7-dias" in r.text and "de=" not in r.text


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
    r = client.get("/relatorios", params={"aba": modelo})
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
    assert f'href="/relatorios?aba={modelo}"' in client.get("/relatorios").text

    # Mexer num filtro mostra "Salvar filtros", que os guarda no modelo.
    r = client.get("/relatorios", params={"aba": modelo, "periodo": "mes-anterior"})
    assert "Salvar filtros" in r.text
    r = client.post(
        f"/relatorios/modelos/{modelo}/filtros",
        data=formulario(client, periodo="mes-anterior"),
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"] == f"/relatorios?aba={modelo}"
    r = client.get("/relatorios", params={"aba": modelo})
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
    assert 'aria-current="page">Primeiro</a>' in client.get("/relatorios").text
    segundo = _criar(client, "Segundo", inicial="1")
    assert 'aria-current="page">Segundo</a>' in client.get("/relatorios").text
    iniciais = db.scalars(select(ReportModel.name).where(ReportModel.is_default)).all()
    assert iniciais == ["Segundo"]

    # A Bia não vê nem mexe nos modelos da Ana.
    entrar(client, "bia@x.com")
    r = client.get("/relatorios", params={"aba": primeiro})
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
    r = client.get("/relatorios")
    assert "Modelo excluído." in r.text and "Segundo" not in r.text
    assert 'aria-current="page">Produtividade</a>' in r.text


def test_csv_de_um_bloco(client: TestClient, cenario: dict[str, Any], db: Session) -> None:
    dia = dia_util_passado()
    numero = registrar(client, cenario, title="Servidor parado")["number"]
    tarefa(client, numero, 90, em(dia, 19))  # 60 min fora do expediente
    tarefa(client, numero, 30, em(dia, 10))
    filtros = _um_dia(dia, aba="horas-extras")
    r = client.get("/relatorios", params=filtros)
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
    r = client.get("/relatorios", params=_um_dia(dia, aba=modelo))
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
    r = client.get("/relatorios", params={"aba": modelo})
    assert "não valem mais para você e ficaram de fora: Pessoa." in r.text
    assert "Por pessoa" in r.text  # o relatório aparece, sem o filtro

    # Um formato que não vale mais: a tela avisa e o editor deixa refazer.
    db.execute(update(ReportModel).where(ReportModel.name == "Antigo").values(config={"x": 1}))
    db.commit()
    r = client.get("/relatorios", params={"aba": modelo})
    assert "Este modelo foi salvo num formato que não vale mais." in r.text
    r = client.get(f"/relatorios/modelos/{modelo}/editar")
    assert r.status_code == 200 and "Este modelo foi salvo num formato" in r.text
