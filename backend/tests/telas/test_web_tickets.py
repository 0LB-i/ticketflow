"""Layout das telas do servidor e lista de chamados com as filas (ADR 0011).

Cenário (a fixture `cenario`): Ana e Bia (supervisora) no TI, Caio na Infra.
"""

import re
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.apoio import API, registrar
from tests.conftest import criar_usuario, entrar


def _numeros(html: str) -> list[int]:
    """Números dos chamados na tabela, na ordem (cada linha tem o link do número)."""
    return [int(n) for n in re.findall(r'class="text-primary underline">(\d+)</a>', html)]


def test_sem_login_vai_para_o_login(client: TestClient, db: Session) -> None:
    assert client.get("/", follow_redirects=False).headers["location"] == "/chamados"
    r = client.get("/chamados", follow_redirects=False)
    assert r.headers["location"] == "/login"  # a tela inicial não precisa de "volta"
    r = client.get("/chamados?aba=todos", follow_redirects=False)
    assert r.headers["location"] == "/login?volta=%2Fchamados%3Faba%3Dtodos"


def test_sessao_expirada_no_meio_do_uso(client: TestClient, db: Session) -> None:
    # Num POST, a "volta" seria aberta com GET depois do login: vai para a tela inicial.
    r = client.post("/chamados/status-em-massa", data={"numeros": [1]}, follow_redirects=False)
    assert r.headers["location"] == "/login"
    # O HTMX ("Carregar mais") troca a página inteira em vez de encaixar o login na tabela.
    r = client.get("/chamados?cursor=x", headers={"HX-Request": "true"}, follow_redirects=False)
    assert r.headers["hx-redirect"] == "/login?volta=%2Fchamados%3Fcursor%3Dx"
    # Com a página de origem (HX-Current-URL), a volta é ela, não o trecho.
    headers = {"HX-Request": "true", "HX-Current-URL": "https://x/chamados?aba=todos"}
    r = client.get("/clientes/opcoes?q=ab", headers=headers, follow_redirects=False)
    assert r.headers["hx-redirect"] == "/login?volta=%2Fchamados%3Faba%3Dtodos"


def test_parametro_invalido_mostra_uma_pagina(client: TestClient, db: Session) -> None:
    criar_usuario(db, grupos={"TI": "member"})
    entrar(client)
    r = client.get("/chamados?cursor=lixo")
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("text/html")
    # No idioma da pessoa.
    client.post("/idioma", data={"csrf_token": client.cookies["tf_csrf"], "locale": "en"})
    assert '<html lang="en">' in client.get("/chamados?cursor=lixo").text
    assert client.get("/api/v1/tickets?cursor=lixo").headers["content-type"] == (
        "application/problem+json"
    )


def test_endereco_inexistente_fora_da_api_da_a_pagina_de_erro(client: TestClient) -> None:
    # Sem a SPA, nenhum endereço cai num index.html: fora de /api, a página de erro das telas.
    for caminho in ("/uma/rota/qualquer", "/sem-acesso", "/assets/app.js"):
        r = client.get(caminho)
        assert r.status_code == 404
        assert r.headers["content-type"].startswith("text/html")
        assert "Não encontrado" in r.text


def test_senha_provisoria_leva_a_troca(client: TestClient, db: Session) -> None:
    criar_usuario(db, trocar_senha=True)
    entrar(client)
    r = client.get("/chamados", follow_redirects=False)
    assert r.headers["location"] == "/trocar-senha"


def test_layout_menu_conforme_permissao(client: TestClient, db: Session) -> None:
    criar_usuario(db, nome="Ana Souza", grupos={"TI": "member"})
    entrar(client)
    r = client.get("/chamados")
    assert r.status_code == 200
    assert "<title>Chamados · TicketFlow</title>" in r.text
    assert '<meta name="fuso" content="America/Sao_Paulo">' in r.text  # para o chamado.js
    assert 'href="/chamados" class="flex h-10' in r.text
    assert 'aria-current="page"' in r.text
    assert "/chamados/novo" in r.text  # agente registra
    assert "/admin/usuarios" not in r.text  # e não administra
    assert "Ana Souza" in r.text

    criar_usuario(db, "admin@exemplo.com", "admin", nome="Admin")
    entrar(client, "admin@exemplo.com")
    r = client.get("/chamados")
    assert "/admin/usuarios" in r.text
    assert "/admin/configuracoes" in r.text
    assert "/admin/clientes" not in r.text  # só o grupo Administradores


def test_filas_contadores_e_filtros(client: TestClient, cenario: dict[str, Any]) -> None:
    meu = registrar(client, cenario, title="Comigo")["number"]
    parado = registrar(client, cenario, title="Parado")["number"]
    client.post(f"{API}/{parado}/transitions", json={"action": "wait", "comment": "Esperando"})
    da_bia = registrar(client, cenario, title="Com a Bia", assignee=cenario["bia"])["number"]

    r = client.get("/chamados")  # sem aba: Meus
    assert _numeros(r.text) == [meu, parado]
    assert 'aria-current="page">\n      Meus' in r.text
    assert (
        '<span class="rounded-full bg-surface-raised px-2 text-sm tabular-nums">2</span>' in r.text
    )

    assert _numeros(client.get("/chamados?aba=aguardando").text) == [parado]
    assert _numeros(client.get("/chamados?aba=todos").text) == [meu, parado, da_bia]
    assert _numeros(client.get("/chamados?aba=todos&status=waiting").text) == [parado]
    assert _numeros(client.get("/chamados?aba=todos&responsavel=eu").text) == [meu, parado]
    # Status e responsável só valem na aba Todos.
    assert _numeros(client.get("/chamados?aba=meus&status=waiting").text) == [meu, parado]
    r = client.get(f"/chamados?aba=todos&grupo={cenario['infra']}")
    assert "Nenhum chamado encontrado." in r.text
    assert _numeros(client.get("/chamados?aba=todos&grupo=invalido").text) == [meu, parado, da_bia]


def test_quem_nao_tem_grupo_comeca_em_todos(
    client: TestClient,
    cenario: dict[str, Any],
) -> None:
    numero = registrar(client, cenario)["number"]
    entrar(client, "auditor@x.com")
    r = client.get("/chamados")
    assert 'aria-current="page">\n      Todos' in r.text
    assert _numeros(r.text) == [numero]


def test_busca(client: TestClient, cenario: dict[str, Any]) -> None:
    impressora = registrar(client, cenario, title="Impressora travada")["number"]
    registrar(client, cenario, title="Monitor apagado")
    r = client.get("/chamados?aba=todos&q=%231234", follow_redirects=False)
    assert r.headers["location"] == "/chamados/1234"
    r = client.get("/chamados?aba=todos&q=impressora")
    assert _numeros(r.text) == [impressora]
    assert "Resultados da busca por “impressora”" in r.text
    assert 'href="/chamados?aba=todos"' in r.text  # limpar a busca


def test_carregar_mais(client: TestClient, cenario: dict[str, Any]) -> None:
    numeros = [registrar(client, cenario)["number"] for _ in range(51)]
    r = client.get("/chamados")
    assert _numeros(r.text) == numeros[:50]
    proxima = r.text.split('hx-get="')[1].split('"')[0].replace("&amp;", "&")
    assert _numeros(client.get(proxima).text) == numeros[50:]


def test_status_em_massa(client: TestClient, cenario: dict[str, Any]) -> None:
    status = {s["name"]: s["id"] for s in client.get("/api/v1/statuses").json()["items"]}
    a = registrar(client, cenario)["number"]
    b = registrar(client, cenario)["number"]
    # Ana não supervisiona: a lista não tem a seleção.
    assert 'id="em-massa"' not in client.get("/chamados").text

    entrar(client, "bia@x.com")
    assert 'id="em-massa"' in client.get("/chamados?aba=todos").text
    dados = {
        "numeros": [a, b, 9999],
        "status_id": status["Concluído"],
        "csrf_token": client.cookies["tf_csrf"],
        "volta": "/chamados?aba=todos",
    }
    assert (
        client.post("/chamados/status-em-massa", data={**dados, "csrf_token": "x"}).status_code
        == 403
    )
    r = client.post("/chamados/status-em-massa", data=dados, follow_redirects=False)
    assert r.headers["location"] == "/chamados?aba=todos"
    r = client.get("/chamados?aba=todos")
    assert "Chamados alterados: 2" in r.text
    assert "Não mudaram: #9999 (Chamado não encontrado.)" in r.text
    assert "Chamados alterados" not in client.get("/chamados?aba=todos").text  # aviso some
    assert client.get(f"{API}/{a}").json()["status"]["name"] == "Concluído"

    r = client.post("/chamados/status-em-massa", data={**dados, "status_id": 99})
    assert 'data-aviso="error"' in r.text
    assert "Chamados alterados" not in r.text

    # Mais de 200 de uma vez: a API recusa, e a tela avisa.
    r = client.post("/chamados/status-em-massa", data={**dados, "numeros": list(range(1, 202))})
    assert "Selecione no máximo 200 chamados de cada vez." in r.text
    # Muitas falhas: o aviso lista as 10 primeiras (o cookie do aviso tem limite de 4 KB).
    r = client.post("/chamados/status-em-massa", data={**dados, "numeros": list(range(1, 16))})
    assert "#10 (Chamado não encontrado.) e mais 5" in r.text


def test_idioma_da_pessoa(client: TestClient, db: Session) -> None:
    user = criar_usuario(db, grupos={"TI": "member"})
    entrar(client)
    csrf = client.cookies["tf_csrf"]
    dados = {"csrf_token": csrf, "locale": "en", "volta": "/chamados?aba=todos"}
    r = client.post("/idioma", data=dados, follow_redirects=False)
    assert r.headers["location"] == "/chamados?aba=todos"
    r = client.get("/chamados")
    assert '<html lang="en">' in r.text
    assert "<title>Tickets · TicketFlow</title>" in r.text

    client.post("/idioma", data={**dados, "locale": "padrao"})
    db.refresh(user)
    assert user.locale is None
    client.post("/idioma", data={**dados, "locale": "fr"})  # ignorado
    db.refresh(user)
    assert user.locale is None
