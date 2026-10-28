"""Tela dos relatórios no servidor (ADR 0011, docs/14 §14.7 e §14.8).

Cenário (a fixture `cenario`): Ana e Bia (supervisora) no TI, Caio na Infra. O escopo é decidido
pela API (`reports/service.resolve`); a tela repassa os filtros e mostra o erro.
"""

import csv
import io
import re
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
from chamados.modules.reports.builder import BUILTINS, relative_period, with_discount, year_before
from chamados.modules.system.models import SystemSetting, WorkSchedule
from chamados.modules.tickets.models import Ticket
from chamados.web.formatting import TIMEZONE, format_day, format_month
from chamados.web.reports_blocks import wide
from chamados.web.reports_state import parse_minutes
from tests.apoio import API, dia_util_passado, em, registrar, status_id, tarefa
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


def test_filtros_desligados_em_configuracoes(
    client: TestClient, cenario: dict[str, Any], db: Session
) -> None:
    """Desligado em Configurações, o campo some da tela; o cliente fica sempre."""
    entrar(client, "bia@x.com")
    r = client.get("/relatorios")
    for campo in ('id="campo-periodo"', 'name="comparar"', "Todos os grupos", "Todas as pessoas"):
        assert campo in r.text
    assert "Todos os status" in r.text
    db.add(
        SystemSetting(
            key="report_filters",
            value={"period": False, "team": False, "person": False, "status": False},
        )
    )
    db.commit()
    r = client.get("/relatorios")
    for campo in ('id="campo-periodo"', "Todos os grupos", "Todas as pessoas", "Todos os status"):
        assert campo not in r.text
    assert 'name="comparar"' in r.text  # sem a chave, ligado
    assert "Todos os clientes" in r.text


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
    # O detalhar a partir dos N dias volta a eles.
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


# --- blocos (docs/14 §14.8) ------------------------------------------------------------------


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
    (aba,) = _links(r.text, "Clientes</a>")
    assert "comparar=anterior" in aba

    # A coluna do dia aplica o dia como período; a barra da pessoa, a pessoa.
    de = f"de={dia.isoformat()}&amp;ate={dia.isoformat()}"
    assert re.search(
        rf'<a href="/relatorios\?[^"]*periodo=personalizado&amp;{de}[^"]*" hx-boost="true"'
        " aria-label",
        r.text,
    )
    assert f"pessoa={cenario['ana']}" in r.text


# --- PDF da aba (docs/14 §14.8.6) ------------------------------------------------------------


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
    assert achado, "sem o link do PDF da aba"
    return achado.group(1).replace("&amp;", "&")


def test_pdf_da_aba(
    client: TestClient, cenario: dict[str, Any], db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    dia = dia_util_passado()
    numero = registrar(client, cenario)["number"]
    tarefa(client, numero, 90, em(dia, 19))

    # Todas as abas, inclusive as de horas, baixam o PDF com os blocos (a API continua com o dela).
    for aba in ("produtividade", "chamados"):
        r = client.get("/relatorios/blocos", params={"aba": aba})
        assert "/relatorios/pdf?" in r.text and "/api/v1/reports/pdf" not in r.text
    r = client.get("/relatorios/blocos", params=_um_dia(dia, comparar="1"))
    link = _link_pdf(r.text)
    assert client.get(link).content.startswith(b"%PDF-1")  # desenhado de verdade
    chamadas = _capturar(monkeypatch, "render_model")
    r = client.get(link)
    assert r.status_code == 200 and r.content == b"%PDF-teste"
    assert r.headers["content-type"] == "application/pdf"
    titulo, linhas, blocos, pagina, cores, logo, empresa = chamadas[0]
    assert titulo == ""  # sem título: o nome da aba não vai para o PDF
    assert cores == ("#C2410C", "#D3785C")
    anterior = (dia - timedelta(days=1)).strftime("%d/%m/%Y")
    # A descrição da aba e, numa linha só, o período, o comparado e os filtros (nenhum aqui).
    assert linhas[0] == "Horas, horas extras, tarefas e chamados concluídos de cada pessoa."
    assert linhas[1] == (
        f"Período: {dia:%d/%m/%Y} a {dia:%d/%m/%Y} · Comparado com {anterior} a {anterior}"
    )
    assert [type(b).__name__ for b in blocos] == ["Cards", "Chart", "Chart", "Grid"]
    assert blocos[0].items[0][:2] == ("Horas", "1h30")
    assert blocos[1].kind == "columns" and blocos[1].points[0][1:] == (90, "1h30")
    # Comparando, a tabela tem a variação (sem base: vazia), na coluna Δ como na tela.
    assert blocos[3].columns[:3] == ["Pessoa", "Horas", "Δ"]
    assert blocos[3].rows[0][:3] == ["Ana", "1h30", ""] and blocos[3].total[:2] == ["1h30", ""]
    # O rodapé de cada página: quando foi gerado (sem quem gerou) e o número da página.
    assert "Ana" not in pagina.generated and pagina.numbering == "Página {n} de {total}"
    assert pagina.continued == "{titulo} (continuação)"
    # Sem o logotipo dos relatórios e sem os dados da empresa, nada; com eles, no cabeçalho.
    assert logo is None and empresa == []
    db.add(
        SystemSetting(
            key="report_logo",
            value={"data": "aGVsbG8=", "content_type": "image/png", "sha256": "x"},
        )
    )
    db.add(SystemSetting(key="company", value={"name": "TI Ltda", "document": "11222333000181"}))
    db.commit()
    client.get(link)
    assert chamadas[-1][5] == b"hello"
    assert chamadas[-1][6] == ["TI Ltda", "CNPJ 11.222.333/0001-81"]
    registro = db.scalars(
        select(AuditLog).where(AuditLog.action == "report.exported").order_by(AuditLog.id)
    ).all()[-1]
    assert (registro.after or {})["format"] == "pdf" and (registro.after or {})["table"] == "model"


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
    # Um cliente por tabela, pelo nome; cada tarefa com o dia, o chamado e o tempo, e o total
    # (as horas no plano e as excedentes só nos cartões do resumo). O chamado em aberto fica de
    # fora, como no resumo.
    (mercado_, padaria_), resumo = blocos[:2], blocos[2:]
    assert isinstance(mercado_, model_pdf.Grid) and isinstance(padaria_, model_pdf.Grid)
    assert (mercado_.title, padaria_.title) == ("Mercado Bom Preço", "Padaria Pão Quente")
    assert mercado_.columns == ["Quando", "Chamado", "Tempo"]
    um, dois = dia.strftime("%d/%m/%Y"), (dia + timedelta(days=1)).strftime("%d/%m/%Y")
    caixa = f"#{numeros['Caixa travado']} Caixa travado"
    assert mercado_.rows == [[um, caixa, "1h30"]]
    assert padaria_.rows == [
        [um, f"#{numeros['Forno parado']} Forno parado", "1h30"],
        [dois, f"#{numeros['Forno parado']} Forno parado", "30min"],
    ]
    assert (padaria_.total_label, padaria_.total) == ("Total", ["", "2h"])
    # No fim, os blocos do simplificado, com o título do resumo. Sem a hora extra: nem nos
    # cartões, nem a frase do expediente no cabeçalho.
    assert len(resumo) == len(simples) and resumo[0].title == "Resumo do período"
    assert isinstance(resumo[0], model_pdf.Cards)
    assert "Horas extras" not in [rotulo for rotulo, _, _ in resumo[0].items]
    assert not any(linha.startswith("Hora extra é") for linha in chamadas[1][1])
    # Com um cliente só no filtro, sem os blocos por cliente (as barras dos maiores e a tabela
    # no fim teriam só ele): ficam os cartões.
    assert [type(b).__name__ for b in simples] == ["Cards", "Chart", "Grid"]
    client.get("/relatorios/pdf", params={**filtros, "cliente": padaria})
    _, _, um_cliente, *_ = chamadas[-1]
    assert [type(b).__name__ for b in um_cliente] == ["Cards"]

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
        "Tempo",
    ]
    assert mercado_.rows == [[um, caixa, "30min", "1h", "1h30"]]
    assert mercado_.total == ["", "30min", "1h", "1h30"]
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
    excedente. As horas descontadas da tela (com um cliente só) abatem das horas."""
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
            ["03/03/2026", f"#{numeros[padrao]} Rede", "1h"],
            ["04/03/2026", f"#{numeros[padrao]} Rede", "45min"],
        ],
        ["", "1h45"],
    )
    # O plano de cada cliente, na tabela por cliente do resumo: as horas, as no plano e as
    # excedentes.
    por_cliente = {linha[0]: linha[1:4] for linha in blocos[-1].rows}
    assert por_cliente["Cliente Padrão"] == ["1h45", "30min", "1h15"]
    assert por_cliente["Mercado Bom Preço"] == ["1h", "30min", "30min"]
    assert por_cliente["Loja Avulsa"] == ["40min", "0min", "40min"]
    assert por_cliente["Sem cliente"] == ["20min", "0min", "20min"]
    resumo = next(b for b in blocos if isinstance(b, model_pdf.Cards))
    valores = {rotulo: valor for rotulo, valor, _ in resumo.items}
    assert (valores["Horas"], valores["Horas no plano"], valores["Horas excedentes"]) == (
        "3h45",
        "1h",
        "2h45",
    )
    assert "Horas descontadas" not in valores

    # As horas descontadas: o campo só aparece com um cliente só; o desconto abate as primeiras
    # horas do período (no plano ou não), e a tela ganha o desconto e as horas a cobrar; as
    # barras mostram as horas a cobrar.
    r = client.get("/relatorios/blocos", params=filtros)
    assert 'name="desconto"' not in r.text
    um_cliente = {**filtros, "cliente": padrao}
    r = client.get("/relatorios/blocos", params=um_cliente)
    assert '<input id="campo-desconto" name="desconto" value=""' in r.text
    r = client.get("/relatorios/blocos", params={**um_cliente, "desconto": "1h"})
    assert re.search(r"<dt[^>]*>Horas a cobrar</dt>", r.text)
    medidas = [b.measures for b in with_discount(BUILTINS["clientes"]).blocks]
    assert medidas[0][:3] == ["hours", "discounted", "charged"] and medidas[1] == ["charged"]
    (detalhado,) = _links(r.text, "PDF detalhado")
    assert parse_qs(urlsplit(detalhado).query)["desconto"] == ["1h"]
    client.get(detalhado)
    _, _, blocos, *_ = chamadas[-1]
    padrao_ = blocos[0]
    assert isinstance(padrao_, model_pdf.Grid)
    assert padrao_.columns == [
        "Quando",
        "Chamado",
        "Tempo",
        "Horas descontadas",
        "Horas a cobrar",
    ]
    assert [linha[2:] for linha in padrao_.rows] == [
        ["1h", "1h", "0min"],
        ["45min", "0min", "45min"],
    ]
    assert padrao_.total == ["", "1h45", "1h", "45min"]
    resumo = next(b for b in blocos if isinstance(b, model_pdf.Cards))
    valores = {rotulo: valor for rotulo, valor, _ in resumo.items}
    assert (valores["Horas descontadas"], valores["Horas a cobrar"]) == ("1h", "45min")
    # O que não se entende fica de fora, com o aviso.
    r = client.get("/relatorios/blocos", params={**um_cliente, "desconto": "uma hora"})
    assert "Use horas e minutos, ex.: 2:30." in r.text
    assert not re.search(r"<dt[^>]*>Horas a cobrar</dt>", r.text)


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
    assert r.text.index('<nav aria-label="Abas de relatório"') < r.text.index('<form method="get"')


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
    # "Limpar" tira todos e mantém a aba e o período.
    (limpar,) = _links(r.text, "Limpar filtros")
    assert parse_qs(urlsplit(limpar).query) == {"periodo": ["mes-atual"], "aba": ["produtividade"]}
    assert "Filtrado por:" not in client.get(limpar).text


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
    assert '<nav aria-label="Abas de relatório" hx-boost="true"' in r.text
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
    (aba,) = _links(r.text, "Clientes</a>")
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
    assert wide(["bars", "columns", "line", "columns"]) == [False] * 4


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
        "bia@x.com": " 08:00–12:00, 13:30–18:00), o do grupo TI (1 pessoa) e o próprio de Ana, sem",
        "ana@x.com": " 08:00–12:00, 13:30–18:00) e o próprio de Ana, sem",
        "admin@x.com": " 08:00–12:00, 13:30–18:00), o do grupo TI (1 pessoa) e o próprio de"
        " 2 pessoas (Ana, Caio), sem",
    }
    chamadas = _capturar(monkeypatch, "render_model")
    for email, texto in esperado.items():
        entrar(client, email)
        r = client.get("/relatorios/blocos", params=_um_dia(dia, aba="horas-extras"))
        assert "Hora extra é o tempo de tarefa" not in r.text, email  # só no PDF
        client.get(_link_pdf(r.text))
        assert (inicio + texto) in chamadas[-1][1][-1], email
