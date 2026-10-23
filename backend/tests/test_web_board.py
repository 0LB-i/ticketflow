"""Quadro (kanban) dos chamados: quem vê o quê e a mudança de status pelo cartão.

Cenário do test_chamados: Ana e Bia (supervisora) no TI, Caio na Infra.
"""

import re
from datetime import datetime, timedelta
from html import unescape
from typing import Any
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import text, update
from sqlalchemy.orm import Session

from chamados.modules.tickets.models import Ticket
from tests.conftest import entrar
from tests.test_chamados import API, base, cenario, registrar  # noqa: F401


def _colunas(html: str) -> dict[str, list[int]]:
    """Os números dos chamados de cada coluna, na ordem das colunas."""
    colunas: dict[str, list[int]] = {}
    for parte in html.split('data-coluna="')[1:]:
        nome = re.search(r'<h2 id="coluna-\d+"[^>]*>\s*(.*?)\s*<span', parte, re.S)
        assert nome
        colunas[nome.group(1)] = [int(n) for n in re.findall(r'tabular-nums">#(\d+)</span>', parte)]
    return colunas


def _cartao(html: str, numero: int) -> str:
    achado = re.search(rf'action="/chamados/{numero}/status".*?</form>', html, re.S)
    assert achado, f"o cartão #{numero} não se move"
    return achado.group(0)


def _destinos(html: str, numero: int) -> dict[str, str]:
    """Nome → id dos status para onde o cartão pode ir (as colunas de `data-destinos`)."""
    ids = re.search(r'data-destinos="([\d ]*)"', _cartao(html, numero))
    assert ids
    nomes = dict(re.findall(r'<h2 id="coluna-(\d+)"[^>]*>\s*(.*?)\s*<span', html, re.S))
    return {nomes[id_]: id_ for id_ in ids.group(1).split()}


def _form(client: TestClient, **dados: Any) -> dict[str, Any]:
    return {"csrf_token": client.cookies["tf_csrf"], **dados}


def test_sem_login_vai_para_o_login(client: TestClient, db: Session) -> None:
    assert client.get("/quadro", follow_redirects=False).headers["location"] == (
        "/login?volta=%2Fquadro"
    )


def test_cada_um_ve_os_seus_e_o_supervisor_os_do_grupo(
    client: TestClient,
    cenario: dict[str, Any],  # noqa: F811
) -> None:
    meu = registrar(client, cenario, title="Comigo")["number"]
    da_bia = registrar(client, cenario, title="Com a Bia", assignee=cenario["bia"])["number"]
    junto = registrar(client, cenario, title="Juntos", assignee=cenario["bia"])["number"]
    client.put(f"{API}/{junto}/assignees", json={"assignee_ids": [cenario["bia"], cenario["ana"]]})

    r = client.get("/quadro")
    assert r.status_code == 200
    assert 'href="/quadro" class="flex h-10' in r.text  # no menu, marcado
    # Uma coluna por status, na ordem das Configurações, e o Cancelado por último. A Ana não vê
    # o chamado só da Bia, mas vê aquele em que também é responsável.
    assert _colunas(r.text) == {
        "Pendente": [meu, junto],
        "Aguardando cliente": [],
        "Entregue": [],
        "Concluído": [],
        "Cancelado": [],
    }
    # Mais de um responsável: o principal e "+1", com todos ao passar o mouse.
    assert '<span class="text-blue-fg" title="Bia, Ana">Bia +1</span>' in r.text
    assert 'name="responsavel"' not in r.text  # sem o filtro: só vê o próprio quadro
    assert list(_destinos(r.text, meu)) == [
        "Aguardando cliente",
        "Entregue",
        "Concluído",
        "Cancelado",
    ]
    assert 'name="volta" value="/quadro"' in _cartao(r.text, meu)
    # A coluna do cancelado tem o fundo avermelhado.
    cancelado = _destinos(r.text, meu)["Cancelado"]
    assert re.search(rf'data-coluna="{cancelado}" class="[^"]*bg-danger/20', r.text)
    assert "Mover para" not in r.text
    assert (
        'Cliente Padrão · <span class="text-blue-fg">Ana</span>' in r.text
    )  # empresa sem nome fantasia: a razão social
    assert re.search(r"Alterado em \d\d/\d\d/\d{4}", r.text)

    entrar(client, "bia@x.com")
    r = client.get("/quadro")
    assert _colunas(r.text)["Pendente"] == [meu, da_bia, junto]
    assert f'<option value="{cenario["ana"]}">Ana</option>' in r.text
    r = client.get(f"/quadro?responsavel={cenario['ana']}")
    assert _colunas(r.text)["Pendente"] == [meu, junto]
    assert 'name="volta" value="/quadro?responsavel=' + cenario["ana"] + '"' in r.text
    # Responsável que não está no quadro: o filtro não vale.
    r = client.get(f"/quadro?responsavel={cenario['caio']}")
    assert _colunas(r.text)["Pendente"] == [meu, da_bia, junto]

    # Caio (Infra) não é responsável por nenhum e não supervisiona o TI.
    entrar(client, "caio@x.com")
    assert all(not ns for ns in _colunas(client.get("/quadro").text).values())


def test_mover_o_cartao_muda_o_status_e_volta_ao_quadro(
    client: TestClient,
    cenario: dict[str, Any],  # noqa: F811
) -> None:
    numero = registrar(client, cenario)["number"]
    html = client.get("/quadro").text
    versao = re.search(r'name="versao" value="([^"]*)"', _cartao(html, numero))
    assert versao
    dados = _form(
        client, versao=unescape(versao.group(1)), status_id=_destinos(html, numero)["Concluído"]
    )

    r = client.post(
        f"/chamados/{numero}/status", data={**dados, "volta": "/quadro"}, follow_redirects=False
    )
    assert r.headers["location"] == "/quadro"
    r = client.get("/quadro")
    assert "Status alterado" in r.text
    assert _colunas(r.text)["Concluído"] == [numero]
    assert client.get(f"{API}/{numero}").json()["status"]["name"] == "Concluído"

    # Quadro antigo: outra mudança no meio (a versão mudou) não passa.
    dados["status_id"] = _destinos(r.text, numero)["Pendente"]
    r = client.post(f"/chamados/{numero}/status", data={**dados, "volta": "/quadro"})
    assert "O chamado mudou desde que você o abriu" in r.text
    assert _colunas(r.text)["Concluído"] == [numero]

    # Só endereços deste site.
    r = client.post(
        f"/chamados/{numero}/status",
        data={**dados, "volta": "//outro.site"},
        follow_redirects=False,
    )
    assert r.headers["location"] == "/chamados"


def test_entregue_so_o_supervisor_conclui(
    client: TestClient,
    cenario: dict[str, Any],  # noqa: F811
) -> None:
    numero = registrar(client, cenario)["number"]
    client.post(f"/chamados/{numero}/entregar", data=_form(client))
    html = client.get("/quadro").text
    assert _colunas(html)["Entregue"] == [numero]
    assert "Concluído" not in _destinos(html, numero)

    entrar(client, "bia@x.com")
    assert "Concluído" in _destinos(client.get("/quadro").text, numero)


def _mudar_data(db: Session, coluna: str, numero: int, meses: int, horas: int = 0) -> None:
    """A data vai para a meia-noite do dia 1º de `meses` atrás (em São Paulo), menos `horas`."""
    inicio = datetime.now(ZoneInfo("America/Sao_Paulo")).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    for _ in range(meses):
        inicio = (inicio - timedelta(days=1)).replace(day=1)
    db.execute(
        update(Ticket)
        .where(Ticket.number == numero)
        .values({coluna: inicio - timedelta(hours=horas)})
    )
    db.commit()


def test_concluidos_e_cancelados_por_mes(
    client: TestClient,
    db: Session,
    cenario: dict[str, Any],  # noqa: F811
) -> None:
    este, virada, passado, retrasado, cancelado, cancelado_antes, aberto = (
        registrar(client, cenario)["number"] for _ in range(7)
    )
    status = {s["name"]: s["id"] for s in client.get("/api/v1/statuses").json()["items"]}
    for numero in (este, virada, passado, retrasado):
        client.patch(f"{API}/{numero}", json={"status_id": status["Concluído"]})
    for numero in (cancelado, cancelado_antes):
        client.post(f"{API}/{numero}/transitions", json={"action": "cancel"})
    _mudar_data(db, "closed_at", virada, 0)  # meia-noite do dia 1º: já é deste mês
    _mudar_data(db, "closed_at", passado, 0, horas=12)
    _mudar_data(db, "closed_at", retrasado, 1, horas=12)
    _mudar_data(db, "canceled_at", cancelado_antes, 0, horas=12)
    _mudar_data(db, "updated_at", aberto, 2)

    r = client.get("/quadro")
    colunas = _colunas(r.text)
    assert colunas["Concluído"] == [este, virada]
    assert colunas["Cancelado"] == [cancelado]
    assert colunas["Pendente"] == [aberto]  # o aberto fica, por mais parado que esteja
    # Um seletor só, no topo, para as duas colunas (inclusive para quem não tem o filtro).
    assert r.text.count(">Mês atual</option>") == 1
    assert 'name="mes"' in r.text

    r = client.get("/quadro?mes=passado")
    colunas = _colunas(r.text)
    assert colunas["Concluído"] == [passado]
    assert colunas["Cancelado"] == [cancelado_antes]
    assert colunas["Pendente"] == [aberto]
    assert '<option value="passado" selected>Mês passado</option>' in r.text
    assert 'name="volta" value="/quadro?mes=passado"' in r.text  # mudar o status volta aqui

    colunas = _colunas(client.get("/quadro?mes=lixo").text)
    assert colunas["Concluído"] == [este, virada]  # valor desconhecido: o mês atual


def _inicio_do_mes_passado() -> datetime:
    agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
    return (agora.replace(day=1) - timedelta(days=1)).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )


def test_no_mes_passado_as_datas_do_topo(
    client: TestClient,
    db: Session,
    cenario: dict[str, Any],  # noqa: F811
) -> None:
    inicio = _inicio_do_mes_passado()
    ultimo_dia = (inicio.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    concluir, cancelar = (registrar(client, cenario)["number"] for _ in range(2))
    for numero in (concluir, cancelar):
        _mudar_data(db, "started_at", numero, 1)

    # No mês atual, sem as datas.
    html = client.get("/quadro").text
    assert "data-data-de" not in html and 'name="concluir_em"' not in html

    # No mês passado: os dois campos, só com dias dele, e o último de início.
    html = client.get("/quadro?mes=passado").text
    limites = f'min="{inicio:%Y-%m-%d}" max="{ultimo_dia:%Y-%m-%d}"'
    for campo in ("concluir_em", "cancelar_em"):
        assert re.search(
            rf'name="{campo}" type="date" value="{ultimo_dia:%Y-%m-%d}" required[^>]*{limites}',
            html,
        ), campo
    assert 'data-data-de="concluir_em"' in html and 'data-data-de="cancelar_em"' in html
    assert html.count("data-data-de") == 2  # só as duas colunas finais
    assert '<input type="hidden" name="conclusao_hora" value="23:59">' in _cartao(html, concluir)

    # A escolha vem pelo endereço; fora do mês (ou inválida), volta o último dia.
    dia_10 = inicio + timedelta(days=9)
    html = client.get(f"/quadro?mes=passado&concluir_em={dia_10:%Y-%m-%d}&cancelar_em=lixo").text
    assert f'name="concluir_em" type="date" value="{dia_10:%Y-%m-%d}"' in html
    assert f'name="cancelar_em" type="date" value="{ultimo_dia:%Y-%m-%d}"' in html
    hoje = datetime.now(ZoneInfo("America/Sao_Paulo"))
    html = client.get(f"/quadro?mes=passado&concluir_em={hoje:%Y-%m-%d}").text
    assert f'name="concluir_em" type="date" value="{ultimo_dia:%Y-%m-%d}"' in html

    # O que o cartão envia ao soltar: o dia do topo, às 23:59.
    def soltar(numero: int, coluna: str, dia: datetime) -> str:
        versao = re.search(r'name="versao" value="([^"]*)"', _cartao(html, numero))
        assert versao
        dados = _form(
            client,
            versao=unescape(versao.group(1)),
            status_id=_destinos(html, numero)[coluna],
            volta="/quadro?mes=passado",
            conclusao_data=f"{dia:%Y-%m-%d}",
            conclusao_hora="23:59",
        )
        return client.post(f"/chamados/{numero}/status", data=dados).text

    r = soltar(concluir, "Concluído", dia_10)
    assert "Status alterado" in r and _colunas(r)["Concluído"] == [concluir]
    closed_at = client.get(f"{API}/{concluir}").json()["closed_at"]
    assert datetime.fromisoformat(closed_at) == dia_10.replace(hour=23, minute=59)
    r = soltar(cancelar, "Cancelado", ultimo_dia)
    assert _colunas(r)["Cancelado"] == [cancelar]
    canceled_at = client.get(f"{API}/{cancelar}").json()["canceled_at"]
    assert datetime.fromisoformat(canceled_at) == ultimo_dia.replace(hour=23, minute=59)


def test_empresa_aparece_pelo_nome_fantasia(
    client: TestClient,
    db: Session,
    cenario: dict[str, Any],  # noqa: F811
) -> None:
    registrar(client, cenario)
    db.execute(
        text(
            "UPDATE clients SET name = 'Comércio de Papéis Ltda', trade_name = 'Papelaria Central'"
        )
    )
    db.commit()
    html = client.get("/quadro").text
    assert 'Papelaria Central · <span class="text-blue-fg">Ana</span>' in html
    assert "Comércio de Papéis" not in html
    # Pessoa física: o nome completo, mesmo com um nome fantasia gravado.
    db.execute(text("UPDATE clients SET kind = 'person', name = 'João da Silva'"))
    db.commit()
    assert 'João da Silva · <span class="text-blue-fg">Ana</span>' in client.get("/quadro").text
