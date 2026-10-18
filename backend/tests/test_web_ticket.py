"""Telas do servidor de registro e detalhe do chamado (ADR 0011).

Cenário do test_chamados: Ana e Bia (supervisora) no TI, Caio na Infra.
"""

import re
from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import entrar
from tests.test_chamados import API, base, cenario, criar_cliente, registrar  # noqa: F401


def _form(client: TestClient, **dados: Any) -> dict[str, Any]:
    return {"csrf_token": client.cookies["tf_csrf"], **dados}


def _aviso(client: TestClient, numero: int, html: str | None = None) -> str:
    """O texto do aviso que a tela do chamado mostra depois de uma ação (a resposta da ação,
    que já seguiu o redirecionamento, ou a próxima visita ao chamado)."""
    html = html if html is not None else client.get(f"/chamados/{numero}").text
    achado = re.search(r'data-aviso="\w+".*?<p class="font-semibold">(.*?)</p>', html, re.S)
    return achado.group(1) if achado else ""


def _novo(cenario: dict[str, Any], **extra: Any) -> dict[str, Any]:  # noqa: F811
    return {
        "grupo": cenario["ti"],
        "titulo": "Impressora parada",
        "descricao": "Não imprime **nada**",
        "client_id": cenario["cliente"],
        "cliente_nome": "Cliente Padrão",
        "responsaveis": [cenario["ana"]],
        "inicio_ajustado": "0",
        **extra,
    }


# --- registro -----------------------------------------------------------------------------------


def test_tela_de_registro(client: TestClient, cenario: dict[str, Any]) -> None:  # noqa: F811
    r = client.get("/chamados/novo")
    assert r.status_code == 200
    assert "<title>Novo chamado · TicketFlow</title>" in r.text
    assert "tiptap-3.31.4.js" in r.text
    # Ana só está no TI: o grupo já vem escolhido, e ela é a responsável.
    assert f'<option value="{cenario["ti"]}" selected>TI</option>' in r.text
    assert f'name="responsaveis" value="{cenario["ana"]}"' in r.text
    # Trocar de grupo traz os membros dele (o HTMX troca só o trecho #responsaveis).
    r = client.get(f"/chamados/novo?grupo={cenario['ti']}")
    assert f'<option value="{cenario["bia"]}">Bia</option>' in r.text

    entrar(client, "auditor@x.com")
    assert "Você ainda não é membro de nenhum grupo" in client.get("/chamados/novo").text


def test_registro_confere_os_campos(client: TestClient, cenario: dict[str, Any]) -> None:  # noqa: F811
    dados = _novo(cenario, titulo="Oi", client_id="", responsaveis=[])
    r = client.post("/chamados/novo", data=_form(client, **dados))
    assert r.status_code == 422
    assert "Informe um título com pelo menos 3 letras." in r.text
    assert "Escolha o cliente." in r.text
    assert "Escolha pelo menos uma pessoa responsável." in r.text
    assert 'value="Oi"' in r.text  # o que foi digitado continua
    futuro = {"inicio_data": "2099-01-01", "inicio_hora": "10:00", "inicio_ajustado": "1"}
    r = client.post("/chamados/novo", data=_form(client, **_novo(cenario, **futuro)))
    assert "O início não pode ficar no futuro." in r.text
    assert client.post("/chamados/novo", data=_novo(cenario)).status_code == 403  # sem CSRF


def test_registro(client: TestClient, cenario: dict[str, Any]) -> None:  # noqa: F811
    dados = _novo(
        cenario,
        responsaveis=[cenario["bia"], cenario["ana"]],
        observadores=[cenario["caio"]],
        contato="Seu Zé",
        inicio_data="2026-10-01",
        inicio_hora="09:30",
        inicio_ajustado="1",
        mention_ids=[cenario["bia"]],
    )
    r = client.post("/chamados/novo", data=_form(client, **dados), follow_redirects=False)
    assert r.status_code == 303
    numero = int(r.headers["location"].rsplit("/", 1)[1])
    assert _aviso(client, numero) == f"Chamado #{numero} registrado"
    chamado = client.get(f"{API}/{numero}").json()
    # Quem registra fica como principal, se estiver na lista.
    assert chamado["assignee"]["display_name"] == "Ana"
    assert [u["display_name"] for u in chamado["co_assignees"]] == ["Bia"]
    assert {w["display_name"] for w in chamado["watchers"]} == {"Bia", "Caio"}
    assert chamado["beneficiary_name"] == "Seu Zé"
    assert chamado["started_at"].startswith("2026-10-01T12:30")  # 09:30 em São Paulo


def test_opcoes_de_cliente(client: TestClient, cenario: dict[str, Any], db: Any) -> None:  # noqa: F811
    criar_cliente(db, "Padaria Pão Quente", "11222333000181")
    r = client.get("/clientes/opcoes?q=padaria")
    assert 'data-nome="Padaria Pão Quente"' in r.text
    assert "Cliente Padrão" not in r.text
    assert "Nenhum cliente encontrado." in client.get("/clientes/opcoes?q=zzz").text


# --- detalhe ------------------------------------------------------------------------------------


def test_detalhe(client: TestClient, cenario: dict[str, Any]) -> None:  # noqa: F811
    numero = registrar(client, cenario, description="**urgente** <script>x</script>")["number"]
    client.post(
        f"{API}/{numero}/comments", json={"body": "Troquei o toner", "time_spent_minutes": 90}
    )
    r = client.get(f"/chamados/{numero}")
    assert r.status_code == 200
    assert f"<title>#{numero} Impressora não imprime · TicketFlow</title>" in r.text
    assert "<strong>urgente</strong> &lt;script&gt;x&lt;/script&gt;" in r.text
    assert "Troquei o toner" in r.text
    assert '<span class="tabular-nums">1h30</span>' in r.text
    assert f'action="/chamados/{numero}/tarefas"' in r.text  # comenta
    assert "Marcar como entregue" in r.text

    # O auditor vê, mas não altera.
    entrar(client, "auditor@x.com")
    r = client.get(f"/chamados/{numero}")
    assert r.status_code == 200
    assert f'action="/chamados/{numero}/tarefas"' not in r.text
    assert "Marcar como entregue" not in r.text

    entrar(client, "caio@x.com")
    r = client.get(f"/chamados/{numero}")
    assert r.status_code == 403
    assert "Você não tem acesso a este chamado" in r.text
    assert client.get("/chamados/999999").status_code == 404


def test_tarefa_nova_e_reabertura(client: TestClient, cenario: dict[str, Any]) -> None:  # noqa: F811
    numero = registrar(client, cenario)["number"]
    url = f"/chamados/{numero}/tarefas"
    r = client.post(url, data=_form(client, texto="Feito", tempo="01:7"))
    assert r.status_code == 422
    assert "Informe horas e minutos válidos" in r.text
    assert ">Feito</textarea>" in r.text  # o texto não se perde
    r = client.post(url, data=_form(client, texto="", tempo="00:30"))
    assert "Descreva a tarefa feita nesse tempo." in r.text

    r = client.post(url, data=_form(client, texto="Feito", tempo="00:45"), follow_redirects=False)
    assert r.status_code == 303
    assert _aviso(client, numero) == "Tarefa adicionada"
    assert client.get(f"{API}/{numero}").json()["time_spent_minutes"] == 45

    client.post(
        f"/chamados/{numero}/status", data=_form(client, status_id=_status(client, "Concluído"))
    )
    r = client.post(url, data=_form(client, texto="", acao="reopen"))
    assert "Escreva na tarefa o motivo da reabertura." in r.text
    client.post(url, data=_form(client, texto="Voltou a falhar", acao="reopen"))
    assert client.get(f"{API}/{numero}").json()["status"]["kind"] == "open"


def _status(client: TestClient, nome: str) -> str:
    return str(
        next(s["id"] for s in client.get("/api/v1/statuses").json()["items"] if s["name"] == nome)
    )


def test_editar_e_remover_tarefa(client: TestClient, cenario: dict[str, Any]) -> None:  # noqa: F811
    numero = registrar(client, cenario)["number"]
    tarefa = client.post(f"{API}/{numero}/comments", json={"body": "Primeira versão"}).json()["id"]
    r = client.get(f"/chamados/{numero}?editar={tarefa}")
    assert f'action="/chamados/{numero}/tarefas/{tarefa}"' in r.text
    dados = {
        "texto": "Versão corrigida",
        "tempo": "02:00",
        "feita_data": "2026-10-10",
        "feita_hora": "08:00",
        "feita_ajustado": "1",
    }
    r = client.post(
        f"/chamados/{numero}/tarefas/{tarefa}", data=_form(client, **dados), follow_redirects=False
    )
    assert r.headers["location"] == f"/chamados/{numero}#tarefa-{tarefa}"
    comentario = client.get(f"{API}/{numero}/comments").json()["items"][0]
    assert comentario["body"] == "Versão corrigida"
    assert comentario["time_spent_minutes"] == 120
    assert comentario["done_at"].startswith("2026-10-10T11:00")

    # Outra pessoa não edita: a tela nem mostra o formulário.
    entrar(client, "bia@x.com")
    assert (
        f'action="/chamados/{numero}/tarefas/{tarefa}"'
        not in client.get(f"/chamados/{numero}?editar={tarefa}").text
    )
    entrar(client, "ana@x.com")

    assert "Remover esta tarefa?" in client.get(f"/chamados/{numero}?remover={tarefa}").text
    client.post(f"/chamados/{numero}/tarefas/{tarefa}/remover", data=_form(client))
    assert client.get(f"{API}/{numero}/comments").json()["items"] == []


def test_acoes_da_lateral(client: TestClient, cenario: dict[str, Any], db: Any) -> None:  # noqa: F811
    numero = registrar(client, cenario)["number"]
    lateral = f"/chamados/{numero}"

    assert client.post(f"{lateral}/status", data={"status_id": "1"}).status_code == 403  # sem CSRF
    r = client.post(f"{lateral}/atribuir", data=_form(client, assignee=cenario["bia"]))
    assert _aviso(client, numero, r.text) == "Responsável alterado"
    client.post(f"{lateral}/assumir", data=_form(client))
    assert client.get(f"{API}/{numero}").json()["assignee"]["display_name"] == "Ana"

    outro = criar_cliente(db, "Padaria Pão Quente", "11222333000181")
    client.post(f"{lateral}/cliente", data=_form(client, client_id=outro))
    assert client.get(f"{API}/{numero}").json()["client"]["name"] == "Padaria Pão Quente"

    r = client.post(
        f"{lateral}/observadores", data=_form(client, user_id=cenario["caio"], observar="1")
    )
    assert _aviso(client, numero, r.text) == "Observador adicionado"
    client.post(
        f"{lateral}/observadores", data=_form(client, user_id=cenario["caio"], observar="0")
    )
    r = client.post(f"{lateral}/observadores", data=_form(client, user_id="invalido", observar="1"))
    assert _aviso(client, numero, r.text) == "Algo deu errado. Tente de novo."
    assert client.get(f"{API}/{numero}").json()["watchers"] == []

    client.post(f"{lateral}/entregar", data=_form(client))
    assert client.get(f"{API}/{numero}").json()["status"]["kind"] == "delivered"
    r = client.post(f"{lateral}/status", data=_form(client, status_id=_status(client, "Pendente")))
    assert _aviso(client, numero, r.text) == "Status alterado"

    # Transferência: os membros do grupo de destino chegam pela página com ?team_id=.
    assert (
        '<option value="' + cenario["caio"] + '">Caio</option>'
        in client.get(f"{lateral}?team_id={cenario['infra']}").text
    )
    dados = {"team_id": cenario["infra"], "assignee_id": cenario["caio"], "motivo": ""}
    r = client.post(f"{lateral}/transferir", data=_form(client, **dados))
    assert _aviso(client, numero, r.text) == "Algo deu errado. Tente de novo."  # sem motivo
    client.post(f"{lateral}/transferir", data=_form(client, **{**dados, "motivo": "É de rede"}))
    assert client.get(f"{API}/{numero}").json()["team"]["name"] == "Infra"

    entrar(client, "caio@x.com")
    r = client.post(f"{lateral}/cancelar", data=_form(client))
    assert _aviso(client, numero, r.text) == "Chamado cancelado"
    assert client.get(f"{API}/{numero}").json()["status"]["kind"] == "canceled"
