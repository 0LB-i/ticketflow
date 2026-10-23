"""Colisão (F1-S4-08, docs/10 §10.6): ETag nos campos, quem mais está vendo e tarefa nova."""

import re
import uuid
from html import unescape
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from chamados.modules.tickets.presence import TTL_SECONDS, Presence
from tests.apoio import API, aviso, formulario, registrar, status_id
from tests.conftest import criar_usuario, entrar

# --- ETag -------------------------------------------------------------------------------------


def test_etag_protege_os_campos(
    client: TestClient,
    cenario: dict[str, Any],
) -> None:
    url = f"{API}/{registrar(client, cenario)['number']}"
    r = client.get(url)
    etag = r.headers["ETag"]
    assert etag.startswith('"') and r.json()["etag"] == etag

    # O que o PATCH não altera não muda o ETag: tarefa nova, responsáveis.
    client.post(f"{url}/comments", json={"body": "Troquei o toner."})
    ids = [cenario["ana"], cenario["bia"]]
    client.put(f"{url}/assignees", json={"assignee_ids": ids})
    assert client.get(url).headers["ETag"] == etag

    r = client.patch(url, json={"title": "Impressora do 3º andar"}, headers={"If-Match": etag})
    assert r.status_code == 200, r.text
    novo = r.headers["ETag"]
    assert novo != etag and r.json()["etag"] == novo

    # Com o ETag antigo: 412, e nada muda.
    r = client.patch(url, json={"title": "Outro título"}, headers={"If-Match": etag})
    assert r.status_code == 412
    assert r.json()["detail"] == (
        "O chamado foi alterado por outra pessoa. Recarregue e tente de novo."
    )
    assert client.get(url).json()["title"] == "Impressora do 3º andar"
    r = client.patch(
        url,
        json={"title": "Outro título"},
        headers={"If-Match": etag, "Accept-Language": "en"},
    )
    assert r.json()["title"] == "Precondition failed"
    assert r.json()["detail"] == "The ticket was changed by someone else. Reload and try again."

    # Vários ETags, `*` e sem If-Match (como antes) passam.
    r = client.patch(url, json={"title": "Título A"}, headers={"If-Match": f'"x", {novo}'})
    assert r.status_code == 200
    assert client.patch(url, json={"title": "Título B"}, headers={"If-Match": "*"}).is_success
    assert client.patch(url, json={"title": "Título C"}).is_success


def test_status_muda_o_etag(
    client: TestClient,
    cenario: dict[str, Any],
) -> None:
    url = f"{API}/{registrar(client, cenario)['number']}"
    etag = client.get(url).headers["ETag"]
    acao = {"action": "wait", "comment": "Aguardando o fornecedor"}
    assert client.post(f"{url}/transitions", json=acao).status_code == 200
    assert client.patch(url, json={"title": "Outro"}, headers={"If-Match": etag}).status_code == 412


def _versao(html: str) -> str:
    achado = re.search(r'name="versao" value="([^"]*)"', html)
    assert achado, "sem a versão no formulário"
    return unescape(achado.group(1))


def test_tela_nao_sobrescreve_o_que_outro_mudou(
    client: TestClient,
    cenario: dict[str, Any],
) -> None:
    numero = registrar(client, cenario)["number"]
    tela = f"/chamados/{numero}"
    versao = _versao(client.get(tela).text)
    assert versao == client.get(f"{API}/{numero}").headers["ETag"]

    # Outra pessoa muda o chamado depois que a tela abriu.
    entrar(client, "bia@x.com")
    client.patch(
        f"{API}/{numero}", json={"status_id": int(status_id(client, "Aguardando cliente"))}
    )
    entrar(client, "ana@x.com")

    for acao, campo in (("status", {"status_id": status_id(client, "Pendente")}), ("entregar", {})):
        r = client.post(f"{tela}/{acao}", data=formulario(client, versao=versao, **campo))
        assert aviso(client, numero, r.text) == (
            "O chamado mudou desde que você o abriu: confira e tente de novo."
        )
        assert client.get(f"{API}/{numero}").json()["status"]["name"] == "Aguardando cliente"
    dados = formulario(client, versao=versao, client_id=cenario["cliente"])
    r = client.post(f"{tela}/cliente", data=dados)
    assert "O chamado mudou desde que você o abriu" in aviso(client, numero, r.text)

    # Com a versão da tela recarregada, passa.
    versao = _versao(client.get(tela).text)
    data = formulario(client, versao=versao, status_id=status_id(client, "Pendente"))
    r = client.post(f"{tela}/status", data=data)
    assert client.get(f"{API}/{numero}").json()["status"]["name"] == "Pendente"


# --- quem mais está vendo e tarefa nova -------------------------------------------------------


def _pergunta(html: str) -> str:
    """O endereço que a tela pergunta a cada 20 s (hx-get do trecho de presença)."""
    achado = re.search(r'id="presenca"[^>]*hx-get="([^"]+)"', html)
    assert achado, "sem o trecho de presença"
    return unescape(achado.group(1))


def test_quem_mais_esta_vendo(
    client: TestClient,
    cenario: dict[str, Any],
    db: Session,
    app: FastAPI,
) -> None:
    agora = [1000.0]
    app.state.presence = Presence(clock=lambda: agora[0])
    criar_usuario(db, "edu@x.com", nome="Edu", grupos={"TI": "member"})
    numero = registrar(client, cenario)["number"]
    tela = f"/chamados/{numero}"
    assert "também está vendo" not in client.get(tela).text  # a Ana não vê a si mesma

    entrar(client, "bia@x.com")
    html = client.get(tela).text
    assert "Ana também está vendo" in html
    entrar(client, "edu@x.com")
    client.get(tela)
    entrar(client, "bia@x.com")
    r = client.get(_pergunta(html), headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "Ana e Edu também estão vendo" in r.text

    # Quem não pergunta há mais de 45 s sai da lista; quem pergunta continua.
    agora[0] += 30
    entrar(client, "edu@x.com")
    client.get(_pergunta(html))
    agora[0] += 20
    entrar(client, "bia@x.com")
    r = client.get(_pergunta(html))
    assert "Edu também está vendo" in r.text and "Ana" not in r.text

    # Quem não vê o chamado não pergunta.
    entrar(client, "caio@x.com")
    assert client.get(_pergunta(html)).status_code == 403


def test_sessao_expirada_nao_leva_ao_login(
    client: TestClient,
    cenario: dict[str, Any],
) -> None:
    """A aba escondida não pergunta; ao voltar, a sessão pode ter expirado. O trecho para de
    perguntar (286) e não troca a página pelo login, que apagaria o texto do editor."""
    pergunta = _pergunta(client.get(f"/chamados/{registrar(client, cenario)['number']}").text)
    client.cookies.clear()
    r = client.get(pergunta, headers={"HX-Request": "true"})
    assert r.status_code == 286
    assert r.headers["HX-Reswap"] == "none"
    assert "HX-Redirect" not in r.headers


def test_aviso_de_tarefa_nova(
    client: TestClient,
    cenario: dict[str, Any],
) -> None:
    numero = registrar(client, cenario)["number"]
    tela = f"/chamados/{numero}"
    entrar(client, "bia@x.com")
    html = client.get(tela).text
    pergunta = _pergunta(html)
    assert "tarefa nova" not in client.get(pergunta).text

    entrar(client, "ana@x.com")
    client.post(f"{API}/{numero}/comments", json={"body": "Troquei o toner."})
    entrar(client, "bia@x.com")
    r = client.get(pergunta)
    assert "1 tarefa nova" in r.text
    # A pergunta não conta como visita: a tarefa da Ana continua como novidade para a Bia.
    item = next(i for i in client.get(f"{API}?view=all").json()["items"] if i["number"] == numero)
    assert item["has_news"]

    # Enviar com a tela antiga: não grava, mostra a tarefa nova e guarda o texto.
    visto = re.search(r'name="visto_ate" value="([^"]*)"', html)
    assert visto
    dados = formulario(client, texto="Vou verificar o cabo.", visto_ate=unescape(visto.group(1)))
    r = client.post(f"{tela}/tarefas", data=dados)
    assert r.status_code == 422
    assert "Chegou uma tarefa nova enquanto você escrevia: confira e envie de novo." in r.text
    assert "Vou verificar o cabo." in r.text and "Troquei o toner." in r.text
    assert len(client.get(f"{API}/{numero}/comments").json()["items"]) == 1

    # O segundo envio, com a tela que já mostra a tarefa nova, passa.
    visto = re.search(r'name="visto_ate" value="([^"]*)"', r.text)
    assert visto
    dados = formulario(client, texto="Vou verificar o cabo.", visto_ate=unescape(visto.group(1)))
    assert client.post(f"{tela}/tarefas", data=dados).status_code == 200  # seguiu o redirect
    assert len(client.get(f"{API}/{numero}/comments").json()["items"]) == 2
    # As próprias tarefas não contam como novas.
    assert "tarefa nova" not in client.get(_pergunta(client.get(tela).text)).text


def test_presenca_esquece_os_chamados_fechados() -> None:
    """Quem passou do prazo sai de todos os chamados, e o chamado sem ninguém sai da memória."""
    agora = [0.0]
    presenca = Presence(clock=lambda: agora[0])
    for _ in range(50):
        presenca.touch(uuid.uuid4(), 1, "Ana")
    aberto = uuid.uuid4()
    agora[0] += TTL_SECONDS + 1
    assert presenca.touch(aberto, 2, "Bia") == []
    assert list(presenca._seen) == [aberto]
