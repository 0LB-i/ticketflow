"""O Histórico e a cascata da aba Clientes (docs/14 §14.7): os PDFs baixados com um cliente só,
de cada pessoa."""

import re
from datetime import datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from chamados.modules.clients.models import Client
from chamados.modules.reports.models import ReportExport
from chamados.web.formatting import TIMEZONE
from tests.conftest import criar_cliente, entrar, outra_sessao

CLIENTES = {"aba": "clientes", "periodo": "mes-atual"}


def _opcoes(client: TestClient, **params: Any) -> str:
    r = client.get("/relatorios/clientes", params=params)
    assert r.status_code == 200, r.text
    return r.text


def _pdf(client: TestClient, **params: Any) -> None:
    r = client.get("/relatorios/pdf", params=params)
    assert r.status_code == 200, r.text
    assert r.content.startswith(b"%PDF-1")


def test_historico_e_cascata(client: TestClient, cenario: dict[str, Any], db: Session) -> None:
    padrao = cenario["cliente"]
    mercado = criar_cliente(db, "Mercado Bom Preço", "11444777000161")

    # Só o PDF da aba Clientes com um cliente só entra no Histórico: sem cliente e de outra aba,
    # não.
    _pdf(client, **CLIENTES)
    _pdf(client, **{**CLIENTES, "aba": "produtividade", "cliente": padrao})
    _pdf(client, **CLIENTES, cliente=padrao, desconto="1h")
    _pdf(client, **CLIENTES, cliente=mercado, detalhado="1", cascata="1")
    gerados = db.scalars(select(ReportExport).order_by(ReportExport.id)).all()
    assert [g.kind for g in gerados] == ["simple", "detailed"]
    # O período fica com as datas (o "mês atual" seria outro depois), sem a cascata.
    hoje = datetime.now(TIMEZONE).date()
    assert gerados[0].query == {
        "aba": "clientes",
        "periodo": "personalizado",
        "de": hoje.replace(day=1).isoformat(),
        "ate": gerados[0].end_date.isoformat(),
        "cliente": [padrao],
        "desconto": "1h",
    }
    assert gerados[1].query["detalhado"] == "1" and "cascata" not in gerados[1].query

    # A cascata tira da lista os clientes com relatório da pessoa hoje; sem ela, estão todos.
    assert "Cliente Padrão" in _opcoes(client) and "Mercado Bom Preço" in _opcoes(client)
    com_cascata = _opcoes(client, cascata="1")
    assert "Cliente Padrão" not in com_cascata and "Mercado Bom Preço" not in com_cascata
    # O de ontem volta.
    padrao_id = db.scalar(select(Client.id).where(Client.name == "Cliente Padrão"))
    ontem = datetime.now(TIMEZONE) - timedelta(days=1)
    db.execute(
        update(ReportExport).where(ReportExport.client_id == padrao_id).values(created_at=ontem)
    )
    db.commit()
    assert "Cliente Padrão" in _opcoes(client, cascata="1")
    # É de cada pessoa: a Bia vê os dois.
    bia = outra_sessao(client)
    entrar(bia, "bia@x.com")
    assert "Mercado Bom Preço" in _opcoes(bia, cascata="1")

    # A chave fica só na aba Clientes; ligada, a busca de clientes leva a cascata.
    r = client.get("/relatorios/blocos", params=CLIENTES)
    # Uma chave de ligar e desligar (o checkbox com `role=switch`), desligada por padrão.
    assert '<input type="checkbox" role="switch" name="cascata" value="1" aria-labelledby' in r.text
    assert 'hx-get="/relatorios/clientes"' in r.text
    r = client.get("/relatorios/blocos", params={**CLIENTES, "cascata": "1"})
    assert 'name="cascata" value="1" checked' in r.text
    assert 'hx-get="/relatorios/clientes?cascata=1"' in r.text
    r = client.get("/relatorios/blocos", params={**CLIENTES, "aba": "produtividade"})
    assert 'name="cascata"' not in r.text
    # A Clientes geral e o Histórico vêm logo depois da aba Clientes.
    barra = re.search(r'<nav aria-label="Abas de relatório".*?</nav>', r.text, re.S)
    assert barra
    abas = re.findall(r">([^<>]+)</a>", barra.group(0))
    i = abas.index("Clientes")
    assert abas[i + 1 : i + 3] == ["Clientes geral", "Histórico"]

    # O Histórico: o mais recente primeiro, com o link que gera o mesmo PDF de novo.
    r = client.get("/relatorios/historico")
    assert r.status_code == 200
    linhas = re.findall(r'<tr class="border-t border-border">(.*?)</tr>', r.text, re.S)
    assert len(linhas) == 2
    assert "Mercado Bom Preço" in linhas[0] and "Detalhado" in linhas[0]
    assert "Cliente Padrão" in linhas[1] and "Simplificado" in linhas[1]
    link = re.search(r'<a href="(/relatorios/pdf\?[^"]+)"', linhas[0])
    assert link
    assert client.get(link.group(1).replace("&amp;", "&")).content.startswith(b"%PDF-1")
    assert db.scalar(select(ReportExport.kind).order_by(ReportExport.id.desc()).limit(1)) == (
        "detailed"
    )
    # Cada pessoa vê só o seu.
    assert "Nenhum relatório gerado ainda." in bia.get("/relatorios/historico").text
