"""Telas do servidor de registro e detalhe do chamado (ADR 0011).

Cenário (a fixture `cenario`): Ana e Bia (supervisora) no TI, Caio na Infra.
"""

import re
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.apoio import API, anexo, aviso, formulario, registrar, status_id
from tests.conftest import consultas, criar_cliente, criar_usuario, entrar, grupo


def _novo(cenario: dict[str, Any], **extra: Any) -> dict[str, Any]:
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


def test_tela_de_registro(client: TestClient, cenario: dict[str, Any]) -> None:
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
    # Já concluído, só o supervisor registra.
    assert ">Concluído</option>" not in r.text
    entrar(client, "bia@x.com")
    assert ">Concluído</option>" in client.get("/chamados/novo").text

    entrar(client, "auditor@x.com")
    assert "Você ainda não é membro de nenhum grupo" in client.get("/chamados/novo").text


def test_registro_em_grupos_ativos(client: TestClient, cenario: dict[str, Any], db: Any) -> None:
    # Ana também está num grupo inativo: ele não aparece, e o TI continua vindo escolhido.
    criar_usuario(db, "dani@x.com", nome="Dani", grupos={"Antigo": "member"})
    db.execute(text("UPDATE teams SET is_active = false WHERE name = 'Antigo'"))
    db.execute(
        text(
            "INSERT INTO team_members (team_id, user_id, role) SELECT t.id, u.id, 'member' "
            "FROM teams t, users u WHERE t.name = 'Antigo' AND u.email = 'ana@x.com'"
        )
    )
    db.commit()
    r = client.get("/chamados/novo")
    assert ">Antigo</option>" not in r.text
    assert f'<option value="{cenario["ti"]}" selected>TI</option>' in r.text
    # Grupo de que não é membro: não aparece, e o endereço não o escolhe.
    r = client.get(f"/chamados/novo?grupo={cenario['infra']}")
    assert ">Infra</option>" not in r.text
    assert f'<option value="{cenario["ti"]}" selected>TI</option>' in r.text


def test_admin_registra_em_qualquer_grupo_ativo(
    client: TestClient,
    cenario: dict[str, Any],
    db: Any,
) -> None:
    adm = str(criar_usuario(db, "adm@x.com", "admin", nome="Adm").public_id)
    grupo(db, "Antigo").is_active = False
    db.commit()
    entrar(client, "adm@x.com")
    r = client.get("/chamados/novo")
    assert ">TI</option>" in r.text and ">Infra</option>" in r.text
    assert ">Antigo</option>" not in r.text
    assert "Você ainda não é membro" not in r.text
    # Fora dos próprios grupos, quem registra não começa como responsável.
    r = client.get(f"/chamados/novo?grupo={cenario['infra']}")
    assert f'name="responsaveis" value="{adm}"' not in r.text
    assert f'<option value="{cenario["caio"]}">Caio</option>' in r.text

    dados = _novo(cenario, grupo=cenario["infra"], responsaveis=[cenario["caio"]])
    r = client.post("/chamados/novo", data=formulario(client, **dados), follow_redirects=False)
    assert r.status_code == 303, r.text
    chamado = client.get(f"{API}/{r.headers['location'].rsplit('/', 1)[1]}").json()
    assert chamado["team"]["name"] == "Infra"
    assert chamado["assignee"]["display_name"] == "Caio"


def test_registro_confere_os_campos(client: TestClient, cenario: dict[str, Any]) -> None:
    dados = _novo(cenario, titulo="Oi", client_id="", responsaveis=[])
    r = client.post("/chamados/novo", data=formulario(client, **dados))
    assert r.status_code == 422
    assert "Informe um título com pelo menos 3 letras." in r.text
    assert "Escolha o cliente." in r.text
    assert "Escolha pelo menos uma pessoa responsável." in r.text
    assert 'value="Oi"' in r.text  # o que foi digitado continua
    futuro = {"inicio_data": "2099-01-01", "inicio_hora": "10:00", "inicio_ajustado": "1"}
    r = client.post("/chamados/novo", data=formulario(client, **_novo(cenario, **futuro)))
    assert "O início não pode ficar no futuro." in r.text
    assert client.post("/chamados/novo", data=_novo(cenario)).status_code == 403  # sem CSRF


def test_registro(client: TestClient, cenario: dict[str, Any]) -> None:
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
    r = client.post("/chamados/novo", data=formulario(client, **dados), follow_redirects=False)
    assert r.status_code == 303
    numero = int(r.headers["location"].rsplit("/", 1)[1])
    assert aviso(client, numero) == f"Chamado #{numero} registrado"
    chamado = client.get(f"{API}/{numero}").json()
    # Quem registra fica como principal, se estiver na lista.
    assert chamado["assignee"]["display_name"] == "Ana"
    assert [u["display_name"] for u in chamado["co_assignees"]] == ["Bia"]
    assert {w["display_name"] for w in chamado["watchers"]} == {"Bia", "Caio"}
    assert chamado["beneficiary_name"] == "Seu Zé"
    inicio = datetime.fromisoformat(chamado["started_at"])
    assert inicio == datetime(2026, 10, 1, 12, 30, tzinfo=UTC)  # 09:30 em São Paulo


def test_opcoes_de_cliente(client: TestClient, cenario: dict[str, Any], db: Any) -> None:
    criar_cliente(db, "Padaria Pão Quente", "11222333000181")
    r = client.get("/clientes/opcoes?q=padaria")
    assert 'data-nome="Padaria Pão Quente"' in r.text
    assert "Cliente Padrão" not in r.text
    assert "Nenhum cliente encontrado." in client.get("/clientes/opcoes?q=zzz").text


# --- detalhe ------------------------------------------------------------------------------------


def test_detalhe(client: TestClient, cenario: dict[str, Any]) -> None:
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


def test_tarefa_nova_e_reabertura(client: TestClient, cenario: dict[str, Any]) -> None:
    numero = registrar(client, cenario)["number"]
    url = f"/chamados/{numero}/tarefas"
    r = client.post(url, data=formulario(client, texto="Feito", tempo="01:7"))
    assert r.status_code == 422
    assert "Informe horas e minutos válidos" in r.text
    assert ">Feito</textarea>" in r.text  # o texto não se perde
    r = client.post(url, data=formulario(client, texto="", tempo="00:30"))
    assert "Descreva a tarefa feita nesse tempo." in r.text

    r = client.post(
        url, data=formulario(client, texto="Feito", tempo="00:45"), follow_redirects=False
    )
    assert r.status_code == 303
    assert aviso(client, numero) == "Tarefa adicionada"
    assert client.get(f"{API}/{numero}").json()["time_spent_minutes"] == 45

    # Ana (agente) não conclui; Bia (supervisora) conclui
    concluir = {"status_id": status_id(client, "Concluído")}
    client.post(f"/chamados/{numero}/status", data=formulario(client, **concluir))
    assert client.get(f"{API}/{numero}").json()["status"]["kind"] == "open"
    entrar(client, "bia@x.com")
    client.post(f"/chamados/{numero}/status", data=formulario(client, **concluir))
    entrar(client, "ana@x.com")
    r = client.post(url, data=formulario(client, texto="", acao="reopen"))
    assert "Escreva na tarefa o motivo da reabertura." in r.text
    dados = formulario(
        client, texto="Voltou a falhar, @Bia", acao="reopen", mention_ids=cenario["bia"]
    )
    client.post(url, data=dados)
    chamado = client.get(f"{API}/{numero}").json()
    assert chamado["status"]["kind"] == "open"
    # A menção no texto da reabertura vale como numa tarefa comum
    assert {w["id"]: w["kind"] for w in chamado["watchers"]} == {cenario["bia"]: "mentioned"}


def test_tarefa_que_cita_imagem_ja_vinculada(
    client: TestClient,
    cenario: dict[str, Any],
) -> None:
    """Copiar para a tarefa uma imagem da descrição não é "anexo já usado": ela só fica no texto.
    Uma imagem colada agora continua sendo vinculada à tarefa."""
    citada = anexo(client, "descricao.png")
    numero = registrar(
        client,
        cenario,
        description=f"![d](/api/v1/attachments/{citada})",
        attachment_ids=[citada],
    )["number"]
    nova = anexo(client, "nova.png")
    imagem = "![{}](/api/v1/attachments/{})"
    texto = f"Como na descrição: {imagem.format('d', citada)} {imagem.format('n', nova)}"
    r = client.post(
        f"/chamados/{numero}/tarefas", data=formulario(client, texto=texto), follow_redirects=False
    )
    assert r.status_code == 303
    anexos = {a["id"]: a["comment_id"] for a in client.get(f"{API}/{numero}").json()["attachments"]}
    assert anexos[citada] is None  # continua na descrição
    assert anexos[nova] is not None  # foi para a tarefa


def test_editar_e_remover_tarefa(client: TestClient, cenario: dict[str, Any]) -> None:
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
        f"/chamados/{numero}/tarefas/{tarefa}",
        data=formulario(client, **dados),
        follow_redirects=False,
    )
    assert r.headers["location"] == f"/chamados/{numero}#tarefa-{tarefa}"
    comentario = client.get(f"{API}/{numero}/comments").json()["items"][0]
    assert comentario["body"] == "Versão corrigida"
    assert comentario["time_spent_minutes"] == 120
    assert datetime.fromisoformat(comentario["done_at"]) == datetime(2026, 10, 10, 11, tzinfo=UTC)

    # Outra pessoa não edita: a tela nem mostra o formulário.
    entrar(client, "bia@x.com")
    assert (
        f'action="/chamados/{numero}/tarefas/{tarefa}"'
        not in client.get(f"/chamados/{numero}?editar={tarefa}").text
    )
    entrar(client, "ana@x.com")

    assert "Remover esta tarefa?" in client.get(f"/chamados/{numero}?remover={tarefa}").text
    client.post(f"/chamados/{numero}/tarefas/{tarefa}/remover", data=formulario(client))
    assert client.get(f"{API}/{numero}/comments").json()["items"] == []


def test_acoes_da_lateral(client: TestClient, cenario: dict[str, Any], db: Any) -> None:
    numero = registrar(client, cenario)["number"]
    lateral = f"/chamados/{numero}"

    assert client.post(f"{lateral}/status", data={"status_id": "1"}).status_code == 403  # sem CSRF
    r = client.post(
        f"{lateral}/responsaveis", data=formulario(client, responsaveis=[cenario["bia"]])
    )
    assert aviso(client, numero, r.text) == "Responsável alterado"
    client.post(f"{lateral}/assumir", data=formulario(client))
    assert client.get(f"{API}/{numero}").json()["assignee"]["display_name"] == "Ana"

    outro = criar_cliente(db, "Padaria Pão Quente", "11222333000181")
    client.post(f"{lateral}/cliente", data=formulario(client, client_id=outro))
    assert client.get(f"{API}/{numero}").json()["client"]["name"] == "Padaria Pão Quente"

    r = client.post(
        f"{lateral}/observadores", data=formulario(client, user_id=cenario["caio"], observar="1")
    )
    assert aviso(client, numero, r.text) == "Observador adicionado"
    client.post(
        f"{lateral}/observadores", data=formulario(client, user_id=cenario["caio"], observar="0")
    )
    r = client.post(
        f"{lateral}/observadores", data=formulario(client, user_id="invalido", observar="1")
    )
    assert aviso(client, numero, r.text) == "Algo deu errado. Tente de novo."
    assert client.get(f"{API}/{numero}").json()["watchers"] == []

    client.post(f"{lateral}/entregar", data=formulario(client))
    assert client.get(f"{API}/{numero}").json()["status"]["kind"] == "delivered"
    r = client.post(
        f"{lateral}/status", data=formulario(client, status_id=status_id(client, "Pendente"))
    )
    assert aviso(client, numero, r.text) == "Status alterado"

    # Transferência: os membros do grupo de destino chegam pela página com ?team_id=.
    assert (
        '<option value="' + cenario["caio"] + '">Caio</option>'
        in client.get(f"{lateral}?team_id={cenario['infra']}").text
    )
    dados = {"team_id": cenario["infra"], "assignee_id": cenario["caio"], "motivo": ""}
    r = client.post(f"{lateral}/transferir", data=formulario(client, **dados))
    assert aviso(client, numero, r.text) == "Informe o motivo da transferência."
    client.post(
        f"{lateral}/transferir", data=formulario(client, **{**dados, "motivo": "É de rede"})
    )
    assert client.get(f"{API}/{numero}").json()["team"]["name"] == "Infra"

    entrar(client, "caio@x.com")
    r = client.post(f"{lateral}/cancelar", data=formulario(client))
    assert aviso(client, numero, r.text) == "Chamado cancelado"
    assert client.get(f"{API}/{numero}").json()["status"]["kind"] == "canceled"


def _forms_de_responsaveis(html: str, url: str) -> list[tuple[list[str], str]]:
    """Os formulários da lateral que mandam a lista de responsáveis: (o que enviam, o rótulo do
    botão X, ou "" no "Atribuir a")."""
    forms = re.findall(rf'<form method="post" action="{url}"[^>]*>(.*?)</form>', html, re.S)
    return [
        (
            re.findall(r'<input type="hidden" name="responsaveis" value="([^"]+)">', f),
            next(iter(re.findall(r'aria-label="(Remover [^"]+)"', f)), ""),
        )
        for f in forms
    ]


def test_varios_responsaveis_na_lateral(client: TestClient, cenario: dict[str, Any]) -> None:
    numero = registrar(client, cenario)["number"]
    url = f"/chamados/{numero}/responsaveis"
    r = client.get(f"/chamados/{numero}")
    # Quem atribui vê as etiquetas, e não a linha "Responsável"; a única não tem o X.
    assert '<dt class="text-muted">Responsável</dt>' not in r.text
    assert _forms_de_responsaveis(r.text, url) == [([cenario["ana"]], "")]  # a única, sem X
    assert '<option value="*">Todas as pessoas do grupo</option>' in r.text
    assert f'<option value="{cenario["bia"]}">Bia</option>' in r.text

    # O grupo todo entra sem tirar quem já está.
    r = client.post(url, data=formulario(client, responsaveis=[cenario["ana"], "*"]))
    assert aviso(client, numero, r.text) == "Responsável alterado"
    chamado = client.get(f"{API}/{numero}").json()
    assert chamado["assignee"]["display_name"] == "Ana"
    assert [u["display_name"] for u in chamado["co_assignees"]] == ["Bia"]
    r = client.get(f"/chamados/{numero}")
    # O "Atribuir a" reenvia todos; o X de cada um envia os demais.
    ana, bia = cenario["ana"], cenario["bia"]
    assert _forms_de_responsaveis(r.text, url) == [
        ([ana, bia], ""),
        ([bia], "Remover Ana"),
        ([ana], "Remover Bia"),
    ]
    assert '<option value="*">' not in r.text  # não sobrou ninguém de fora

    # Tirar a Ana: a Bia vira a principal.
    client.post(url, data=formulario(client, responsaveis=[cenario["bia"]]))
    chamado = client.get(f"{API}/{numero}").json()
    assert chamado["assignee"]["display_name"] == "Bia" and chamado["co_assignees"] == []

    r = client.post(url, data=formulario(client))  # lista vazia
    assert aviso(client, numero, r.text) == "Algo deu errado. Tente de novo."
    r = client.post(url, data=formulario(client, responsaveis=[cenario["caio"]]))  # de outro grupo
    assert aviso(client, numero, r.text) == "O responsável precisa ser um membro ativo do grupo."

    # Sem assign_others (o auditor): a linha "Responsável", sem o formulário.
    entrar(client, "auditor@x.com")
    r = client.get(f"/chamados/{numero}")
    assert '<dt class="text-muted">Responsável</dt>' in r.text
    assert f'action="{url}"' not in r.text
    r = client.post(url, data=formulario(client, responsaveis=[cenario["ana"]]))
    assert 'data-aviso="error"' in r.text
    assert client.get(f"{API}/{numero}").json()["assignee"]["display_name"] == "Bia"


def test_casos_de_borda_das_acoes(client: TestClient, cenario: dict[str, Any], db: Any) -> None:
    numero = registrar(client, cenario)["number"]
    chamado = f"/chamados/{numero}"

    r = client.post(
        f"{chamado}/transferir", data=formulario(client, team_id=cenario["infra"], motivo="  ")
    )
    assert aviso(client, numero, r.text) == "Informe o motivo da transferência."

    # Status "Entregue" padrão removido com a página aberta: aviso, não erro 500.
    db.execute(
        text("UPDATE ticket_statuses SET is_default_for_kind = false WHERE kind = 'delivered'")
    )
    db.commit()
    try:
        r = client.post(f"{chamado}/entregar", data=formulario(client))
        assert aviso(client, numero, r.text) == "Status não encontrado."
    finally:
        db.execute(
            text(
                "UPDATE ticket_statuses SET is_default_for_kind = true WHERE id = "
                "(SELECT min(id) FROM ticket_statuses WHERE kind = 'delivered')"
            )
        )
        db.commit()

    # Tarefa de outra pessoa ou id inválido: volta ao chamado com o aviso.
    tarefa = client.post(f"{API}/{numero}/comments", json={"body": "Da Ana"}).json()["id"]
    entrar(client, "bia@x.com")
    r = client.post(f"{chamado}/tarefas/{tarefa}", data=formulario(client, texto="Forjado"))
    assert r.url.path == chamado
    assert 'data-aviso="error"' in r.text
    assert "Forjado" not in r.text
    r = client.post(f"{chamado}/tarefas/invalido", data=formulario(client, texto="x"))
    assert aviso(client, numero, r.text) == "Algo deu errado. Tente de novo."


def test_data_ajustada_invalida(client: TestClient, cenario: dict[str, Any]) -> None:
    dados = _novo(cenario, inicio_data="", inicio_hora="10:00", inicio_ajustado="1")
    r = client.post("/chamados/novo", data=formulario(client, **dados))
    assert r.status_code == 422
    assert "Informe uma data e hora válidas." in r.text
    # Status com algarismo que não é ASCII: ignorado, sem erro 500.
    r = client.post("/chamados/novo", data=formulario(client, **_novo(cenario, status_id="²")))
    assert r.status_code == 200  # seguiu para o chamado registrado
    assert r.url.path.startswith("/chamados/")


def test_telas_de_chamado_nao_contam_chamados_por_status(
    client: TestClient,
    cenario: dict[str, Any],
) -> None:
    """A contagem por status percorre todos os chamados: só a tela de Configurações a mostra."""
    numero = registrar(client, cenario)["number"]
    for url in (f"/chamados/{numero}", "/chamados/novo", "/chamados"):
        with consultas(client) as sql:
            assert client.get(url).status_code == 200
        assert not [q for q in sql if "GROUP BY tickets.status_id" in q], url


def test_tela_do_chamado_carrega_o_chamado_uma_vez(
    client: TestClient,
    cenario: dict[str, Any],
) -> None:
    """O detalhe e as tarefas reaproveitam o chamado carregado (com a visibilidade)."""
    numero = registrar(client, cenario)["number"]
    tarefa = client.post(f"{API}/{numero}/comments", json={"body": "Primeira"}).json()["id"]
    for url in (f"/chamados/{numero}", f"/chamados/{numero}?editar={tarefa}"):
        with consultas(client) as sql:
            r = client.get(url)
        assert r.status_code == 200
        assert len([q for q in sql if "WHERE tickets.number = " in q]) == 1, url
    assert ">Primeira</textarea>" in r.text  # a tarefa em edição continua aparecendo
