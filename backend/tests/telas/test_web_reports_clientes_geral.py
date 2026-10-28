"""A aba Clientes geral (docs/14 §14.7): o período e o status e, ao gerar, o relatório detalhado
de cada cliente com horas, com o PDF detalhado dele e o ZIP com o de todos."""

import io
import re
import zipfile
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from chamados.modules.reports.models import ReportExport
from tests.apoio import API, dia_util_passado, em, registrar, tarefa
from tests.conftest import criar_cliente

PAGINA = "/relatorios/clientes-geral"
SEMANA = {"periodo": "semana-anterior"}


def _clientes(html: str) -> list[str]:
    """Os nomes dos clientes gerados, na ordem."""
    return re.findall(r'<h2 class="text-lg font-semibold">([^<]+)</h2>', html)


def test_clientes_geral(client: TestClient, cenario: dict[str, Any], db: Session) -> None:
    seg = dia_util_passado()
    mercado = criar_cliente(db, "Mercado Bom Preço", "11444777000161")
    criar_cliente(db, "Oficina Sem Horas", "11222333000181")

    # Cliente Padrão: concluído, 90 min. Mercado: em aberto, 30 min.
    padrao = registrar(client, cenario, title="Rede lenta")["number"]
    tarefa(client, padrao, 90, em(seg, 10))
    r = client.post(
        f"{API}/{padrao}/transitions",
        json={"action": "close", "comment": "Pronto", "resolution_code_id": 1},
    )
    assert r.status_code == 200, r.text
    aberto = registrar(client, cenario, client_id=mercado, title="Caixa travado")["number"]
    tarefa(client, aberto, 30, em(seg, 14))

    # Sem gerar, só os campos, com o status nos concluídos; a aba aparece ao lado da Clientes.
    r = client.get(PAGINA)
    assert r.status_code == 200, r.text
    assert _clientes(r.text) == []
    assert 'aria-current="page">Clientes geral</a>' in r.text
    assert 'name="gerar" value="1"' in r.text
    concluidos = re.findall(r'<input type="hidden" name="status" value="(\d+)">', r.text)
    assert concluidos

    # Gerando com eles: só o Cliente Padrão, com a tarefa e o PDF.
    r = client.get(PAGINA, params={**SEMANA, "status": concluidos, "gerar": "1"})
    assert r.status_code == 200, r.text
    assert _clientes(r.text) == ["Cliente Padrão"]
    assert "Rede lenta" in r.text and "1h30" in r.text
    # Nas tarefas, só o tempo; as horas no plano e as excedentes, nos cartões depois delas.
    assert '<th scope="col" class="px-3 py-2 font-medium">Horas excedentes</th>' not in r.text
    assert r.text.index("</table>") < r.text.index(">Horas excedentes</dt>")
    pdf = re.search(r'<a href="(/relatorios/pdf\?[^"]+)" download', r.text)
    assert pdf is not None

    # Sem status (todos), os dois com horas, pelo nome; a Oficina, sem horas, não aparece.
    r = client.get(PAGINA, params={**SEMANA, "gerar": "1"})
    assert _clientes(r.text) == ["Cliente Padrão", "Mercado Bom Preço"]

    # O PDF é o detalhado da aba Clientes com o cliente, com o nome dele: entra no Histórico.
    r = client.get(pdf[1].replace("&amp;", "&"))
    assert r.status_code == 200, r.text
    assert r.content.startswith(b"%PDF-1")
    disposicao = r.headers["content-disposition"]
    assert 'filename="Cliente Padrao - relatorio-' in disposicao
    assert "filename*=UTF-8''Cliente%20Padr%C3%A3o%20-%20relatorio-" in disposicao
    gerado = db.scalars(select(ReportExport)).one()
    assert gerado.kind == "detailed" and gerado.query["cliente"] == [cenario["cliente"]]

    # Baixar todos: um ZIP com o PDF de cada cliente com horas, cada um com o nome dele.
    r = client.get(PAGINA, params={**SEMANA, "gerar": "1"})
    zip_url = re.search(r'<a href="(/relatorios/clientes-geral/zip[^"]*)" download', r.text)
    assert zip_url is not None
    r = client.get(zip_url[1].replace("&amp;", "&"))
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(r.content)) as arquivo:
        nomes = sorted(arquivo.namelist())
        assert [n.split(" - ")[0] for n in nomes] == ["Cliente Padrão", "Mercado Bom Preço"]
        assert all(arquivo.read(n).startswith(b"%PDF-1") for n in nomes)
    assert db.scalar(select(func.count()).select_from(ReportExport)) == 3

    # Nenhum cliente com horas no período.
    r = client.get(PAGINA, params={"periodo": "ano-anterior", "gerar": "1"})
    assert "Nenhum cliente com horas no período." in r.text
