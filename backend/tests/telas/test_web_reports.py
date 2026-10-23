"""Tela dos relatórios no servidor (ADR 0011, docs/14 §14.7).

Cenário (a fixture `cenario`): Ana e Bia (supervisora) no TI, Caio na Infra. O escopo é decidido
pela API (`reports/service.resolve`); a tela repassa os filtros e mostra o erro.
"""

import re
from datetime import date, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from chamados.web.formatting import TIMEZONE, format_day, format_month
from tests.apoio import dia_util_passado, em, registrar, tarefa
from tests.conftest import criar_cliente, entrar


def _um_dia(dia: date, **extra: str) -> dict[str, str]:
    return {"periodo": "personalizado", "de": dia.isoformat(), "ate": dia.isoformat(), **extra}


def _pdf(html: str) -> dict[str, list[str]]:
    """Os parâmetros do link "Baixar PDF"."""
    achado = re.search(r'<a href="(/api/v1/reports/pdf\?[^"]+)" download', html)
    assert achado, "sem o link do PDF"
    return parse_qs(urlsplit(achado.group(1).replace("&amp;", "&")).query)


def test_relatorio_do_mes(client: TestClient, cenario: dict[str, Any]) -> None:
    r = client.get("/relatorios")
    assert r.status_code == 200
    assert "<title>Relatórios · TicketFlow</title>" in r.text
    hoje = datetime.now(TIMEZONE).date()
    mes = format_month("pt-BR", hoje)
    assert f'<option value="{hoje:%Y-%m}" selected>{mes}</option>' in r.text
    assert '<option value="personalizado">Personalizado</option>' in r.text
    assert "Chamados registrados" in r.text
    assert 'aria-current="page">Produtividade</a>' in r.text
    pdf = _pdf(r.text)
    assert pdf["start"] == [hoje.replace(day=1).isoformat()]
    assert pdf["locale"] == ["pt-BR"]
    # A Ana só vê o próprio trabalho: não escolhe grupo nem pessoa. O cliente é opcional.
    assert "Todos os grupos" not in r.text
    assert "Todas as pessoas" not in r.text
    assert '<label for="campo-cliente" class="font-medium">Cliente</label>' in r.text

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
    assert "Horas por cliente (os 10 primeiros)" in r.text
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
    assert '<option value="" selected>Todas as pessoas</option>' in r.text
    assert f'<option value="{cenario["ana"]}">Ana</option>' in r.text
    assert "Todos os grupos" in r.text  # supervisiona o TI
    r = client.get("/relatorios", params=_um_dia(dia, pessoa=cenario["ana"], grupo=cenario["ti"]))
    assert f'<option value="{cenario["ana"]}" selected>Ana</option>' in r.text
    assert '<dd class="mt-1 text-2xl font-semibold">30min</dd>' in r.text
    pdf = _pdf(r.text)
    assert pdf["person"] == [cenario["ana"]] and pdf["team"] == [cenario["ti"]]
    # O link leva ao PDF com os mesmos números.
    url = re.search(r'<a href="(/api/v1/reports/pdf\?[^"]+)"', r.text).group(1)  # type: ignore[union-attr]
    resposta = client.get(url.replace("&amp;", "&"))
    assert resposta.status_code == 200
    assert resposta.content.startswith(b"%PDF")


def test_filtro_de_cliente(client: TestClient, cenario: dict[str, Any], db: Session) -> None:
    padaria = criar_cliente(db, "Padaria Pão Quente", "11222333000181")
    # O nome mostrado vem do cadastro, não do que veio na URL.
    r = client.get("/relatorios", params={"client_id": padaria, "cliente_nome": "Outro"})
    assert f'name="client_id" value="{padaria}"' in r.text
    assert 'value="Padaria Pão Quente"' in r.text
    assert 'value="Outro"' not in r.text
    assert 'aria-label="Tirar o cliente"' in r.text and "data-limpa-cliente hidden" not in r.text
    assert _pdf(r.text)["client"] == [padaria]
    # A busca fica fora do formulário de filtros: não vai no envio nem o dispara.
    assert 'name="q" form="sem-formulario"' in r.text
    # Sem cliente, o X fica escondido.
    assert "data-limpa-cliente hidden" in client.get("/relatorios").text


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
    assert f'<option value="{hoje:%Y-%m}" selected>' in r.text
    assert 'aria-current="page">Produtividade</a>' in r.text


def test_formatos_do_relatorio() -> None:
    assert format_month("pt-BR", date(2026, 3, 1)) == "março de 2026"
    assert format_month("en", date(2026, 3, 1)) == "March 2026"
    assert format_day("pt-BR", date(2026, 10, 5)) == "05/10"
    assert format_day("en", date(2026, 10, 5)) == "10/05"
