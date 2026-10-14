"""Chamados pela API (Sprint 3: docs/10). Cenário: Ana e Bia (supervisora) no TI, Caio na Infra."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from chamados.modules.clients.models import Client
from tests.conftest import criar_categoria, criar_usuario, entrar, grupo

API = "/api/v1/tickets"


@pytest.fixture
def cenario(client: TestClient, db: Session) -> dict[str, Any]:
    pessoas = {
        "ana": criar_usuario(db, "ana@x.com", nome="Ana", grupos={"TI": "member"}),
        "bia": criar_usuario(db, "bia@x.com", nome="Bia", grupos={"TI": "supervisor"}),
        "caio": criar_usuario(db, "caio@x.com", nome="Caio", grupos={"Infra": "member"}),
        "auditor": criar_usuario(db, "auditor@x.com", "auditor", nome="Auditor"),
    }
    entrar(client, "ana@x.com")
    return {
        **{nome: str(u.public_id) for nome, u in pessoas.items()},
        "ti": str(grupo(db, "TI").public_id),
        "infra": str(grupo(db, "Infra").public_id),
        "impressao": str(criar_categoria(db, "Impressão", grupo_padrao="TI").public_id),
        "sem_grupo": str(criar_categoria(db, "Diversos", tipo="task").public_id),
    }


def registrar(client: TestClient, c: dict[str, Any], **extra: Any) -> dict[str, Any]:
    dados = {"title": "Impressora não imprime", "category_id": c["impressao"], **extra}
    r = client.post(API, json=dados)
    assert r.status_code == 201, r.text
    result: dict[str, Any] = r.json()
    return result


def eventos(client: TestClient, numero: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = client.get(f"{API}/{numero}/events").json()["items"]
    return result


# --- registro -----------------------------------------------------------------------------------


def test_registro_com_roteamento(client: TestClient, cenario: dict[str, Any]) -> None:
    r = client.post(
        API,
        json={
            "title": "  ERP fora do ar  ",
            "description": "O Financeiro avisou por telefone.",
            "category_id": cenario["impressao"],
            "beneficiary_name": "João Silva",
            "assignee": "me",
        },
    )
    assert r.status_code == 201, r.text
    t = r.json()
    assert r.headers["location"] == f"/api/v1/tickets/{t['id']}"
    assert t["number"] == 1000
    assert t["title"] == "ERP fora do ar"
    assert t["team"]["name"] == "TI"  # grupo padrão da categoria
    assert t["type"] == "incident"
    assert t["status"] == {"id": 1, "name": "Pendente", "kind": "open"}
    assert t["assignee"]["full_name"] == "Ana"
    assert t["created_by"]["full_name"] == "Ana"
    assert t["category"]["path"] == "Impressão"
    assert {"close", "wait", "edit", "transfer"} <= set(t["allowed_actions"])

    assert client.get(f"{API}/{t['id']}").json()["number"] == 1000  # pelo UUID também
    assert [e["type"] for e in eventos(client, 1000)] == ["ticket.created"]


def test_registro_valida_grupo_responsavel_e_perfil(
    client: TestClient, cenario: dict[str, Any], db: Session
) -> None:
    # Categoria sem grupo padrão: precisa escolher o grupo; tipo vem da categoria
    r = client.post(API, json={"title": "Sem grupo", "category_id": cenario["sem_grupo"]})
    assert r.status_code == 422
    t = registrar(client, cenario, category_id=cenario["sem_grupo"], team_id=cenario["ti"])
    assert t["type"] == "task" and t["assignee"] is None

    # Título com menos de 3 letras depois de tirar os espaços
    r = client.post(API, json={"title": "  ab  ", "category_id": cenario["impressao"]})
    assert r.status_code == 422

    # Só nos próprios grupos
    r = client.post(
        API,
        json={"title": "Outro", "category_id": cenario["impressao"], "team_id": cenario["infra"]},
    )
    assert r.status_code == 403
    # Qualquer membro registra para outro membro; o responsável precisa ser do grupo
    assert registrar(client, cenario, assignee=cenario["bia"])["assignee"]["full_name"] == "Bia"
    r = client.post(
        API,
        json={"title": "Caio", "category_id": cenario["impressao"], "assignee": cenario["caio"]},
    )
    assert r.status_code == 422

    entrar(client, "auditor@x.com")
    assert (
        client.post(API, json={"title": "Auditor", "category_id": cenario["impressao"]}).status_code
        == 403
    )


def test_registro_sem_categoria(client: TestClient, cenario: dict[str, Any]) -> None:
    # Sem categoria não há grupo padrão: o grupo é obrigatório
    r = client.post(API, json={"title": "Sem categoria"})
    assert r.status_code == 422
    assert r.json()["detail"] == "Escolha o grupo do chamado."

    r = client.post(API, json={"title": "Sem categoria", "team_id": cenario["ti"]})
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["category"] is None and t["type"] == "incident" and t["team"]["name"] == "TI"
    assert client.get(f"{API}/{t['number']}").json()["category"] is None
    assert client.get(API).json()["items"][0]["category"] is None

    # A categoria pode ser escolhida depois e tirada de novo
    url = f"{API}/{t['number']}"
    assert client.patch(url, json={"category_id": cenario["impressao"]}).json()["category"]
    r = client.patch(url, json={"category_id": None})
    assert r.status_code == 200 and r.json()["category"] is None
    mudancas = eventos(client, t["number"])[-1]["payload"]["changes"]
    assert mudancas["category"] == {
        "from": {"id": cenario["impressao"], "name": "Impressão"},
        "to": None,
    }


def test_inicio_do_chamado(client: TestClient, cenario: dict[str, Any]) -> None:
    # Sem início informado, vale a hora do registro
    t = registrar(client, cenario)
    assert t["started_at"] == t["created_at"]

    # Quem registra pode informar outro início, mas não no futuro
    t = registrar(client, cenario, started_at="2026-10-01T08:30:00-03:00")
    assert datetime.fromisoformat(t["started_at"]) == datetime(2026, 10, 1, 11, 30, tzinfo=UTC)
    futuro = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    r = client.post(
        API, json={"title": "Futuro", "category_id": cenario["impressao"], "started_at": futuro}
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "O início não pode ficar no futuro."
    r = client.post(
        API,
        json={
            "title": "Sem fuso",
            "category_id": cenario["impressao"],
            "started_at": "2026-10-01T08:30:00",
        },
    )
    assert r.status_code == 422

    # E ajustar depois, com registro no histórico
    url = f"{API}/{t['number']}"
    r = client.patch(url, json={"started_at": "2026-10-01T09:00:00-03:00"})
    assert r.status_code == 200 and datetime.fromisoformat(r.json()["started_at"]) == datetime(
        2026, 10, 1, 12, tzinfo=UTC
    )
    mudancas = eventos(client, t["number"])[-1]["payload"]["changes"]
    assert {k: datetime.fromisoformat(v) for k, v in mudancas["started_at"].items()} == {
        "from": datetime(2026, 10, 1, 11, 30, tzinfo=UTC),
        "to": datetime(2026, 10, 1, 12, tzinfo=UTC),
    }
    assert client.patch(url, json={"started_at": futuro}).status_code == 422


def test_em_revisao_so_o_supervisor_entrega(client: TestClient, cenario: dict[str, Any]) -> None:
    status = {s["name"]: s["id"] for s in client.get("/api/v1/statuses").json()["items"]}
    t = registrar(client, cenario, assignee="me")
    url = f"{API}/{t['number']}"
    assert "set_status_closed" in t["allowed_actions"]

    # Ana (responsável) manda para revisão: o chamado fica em espera (kind waiting)
    r = client.patch(url, json={"status_id": status["Em espera de revisão"]})
    assert r.json()["status"]["kind"] == "waiting"
    assert "set_status_closed" not in r.json()["allowed_actions"]
    # Em revisão, ela não entrega nem conclui; outros status, sim
    for nome in ("Entregue", "Concluído"):
        assert client.patch(url, json={"status_id": status[nome]}).status_code == 403
    assert client.get(url).json()["status"]["name"] == "Em espera de revisão"

    # Bia, supervisora do TI, verifica e entrega
    entrar(client, "bia@x.com")
    assert "set_status_closed" in client.get(url).json()["allowed_actions"]
    r = client.patch(url, json={"status_id": status["Entregue"]})
    assert r.status_code == 200 and r.json()["status"]["name"] == "Entregue"


def test_status_escolhido_no_formulario(client: TestClient, cenario: dict[str, Any]) -> None:
    status = {s["name"]: s["id"] for s in client.get("/api/v1/statuses").json()["items"]}
    assert list(status) == [
        "Pendente",
        "Aguardando cliente",
        "Em espera de revisão",
        "Entregue",
        "Concluído",
        "Cancelado",
    ]

    # Sem status, Pendente; com status, qualquer um, sem comentário nem código de resolução
    assert registrar(client, cenario)["status"]["name"] == "Pendente"
    t = registrar(client, cenario, status_id=status["Entregue"])
    assert t["status"] == {"id": status["Entregue"], "name": "Entregue", "kind": "closed"}
    assert t["closed_at"] is not None
    r = client.post(
        API, json={"title": "Status?", "category_id": cenario["impressao"], "status_id": 99}
    )
    assert r.status_code == 422

    # Na edição: entre dois status de conclusão, a data de conclusão não muda
    url = f"{API}/{t['number']}"
    assert "set_status" in t["allowed_actions"]
    r = client.patch(url, json={"status_id": status["Concluído"]})
    assert r.status_code == 200
    assert r.json()["status"]["name"] == "Concluído" and r.json()["closed_at"] == t["closed_at"]
    ultimo = eventos(client, t["number"])[-1]
    assert ultimo["type"] == "ticket.status_changed"
    assert ultimo["payload"]["from"]["name"] == "Entregue"
    assert ultimo["payload"]["to"]["name"] == "Concluído"

    # Voltar para Pendente reabre
    r = client.patch(url, json={"status_id": status["Pendente"]}).json()
    assert r["closed_at"] is None and r["reopened_count"] == 1

    # Quem não muda status no fluxo também não muda no formulário
    entrar(client, "auditor@x.com")
    assert client.patch(url, json={"status_id": status["Cancelado"]}).status_code == 403


# --- edição ------------------------------------------------------------------------------------


def test_edicao_de_campos_vai_para_o_historico(
    client: TestClient, cenario: dict[str, Any], db: Session
) -> None:
    t = registrar(client, cenario)
    r = client.patch(
        f"{API}/{t['number']}",
        json={
            "title": "Impressora do 3º andar",
            "category_id": cenario["sem_grupo"],
            "type": "request",
            "beneficiary_name": "Carla",
        },
    )
    assert r.status_code == 200
    assert r.json()["category"]["name"] == "Diversos"
    mudancas = eventos(client, t["number"])[-1]["payload"]["changes"]
    assert mudancas["title"]["to"] == "Impressora do 3º andar"
    assert mudancas["category"]["from"]["name"] == "Impressão"
    assert mudancas["category"]["to"]["name"] == "Diversos"
    assert mudancas["beneficiary_name"] == {"from": None, "to": "Carla"}

    # Sem mudança, sem evento
    n = len(eventos(client, t["number"]))
    client.patch(f"{API}/{t['number']}", json={"title": "Impressora do 3º andar"})
    assert len(eventos(client, t["number"])) == n

    # O histórico só aceita inserção
    with pytest.raises(ProgrammingError, match="só aceita inserção"):
        db.execute(text("UPDATE ticket_events SET event_type = 'x'"))
    db.rollback()


def criar_cliente(db: Session, nome: str, documento: str, *, ativo: bool = True) -> str:
    cliente = Client(
        kind="company",
        name=nome,
        document=documento,
        email="contato@x.com",
        phone="1133334444",
        postal_code="01310100",
        street="Avenida Paulista",
        number="1000",
        district="Bela Vista",
        city="São Paulo",
        state="SP",
        is_active=ativo,
    )
    db.add(cliente)
    db.commit()
    return str(cliente.public_id)


def test_cliente_e_contato_do_chamado(
    client: TestClient, cenario: dict[str, Any], db: Session
) -> None:
    padaria = criar_cliente(db, "Padaria Pão Quente", "11222333000181")
    mercado = criar_cliente(db, "Mercado Bom Preço", "11444777000161")
    antigo = criar_cliente(db, "Cliente Antigo", "12ABC34501DE35", ativo=False)

    t = registrar(client, cenario, client_id=padaria, beneficiary_name="  Maria  ")
    assert t["client"] == {"id": padaria, "name": "Padaria Pão Quente"}
    assert t["beneficiary_name"] == "Maria"
    lista = client.get(API).json()["items"]
    assert lista[0]["client"]["name"] == "Padaria Pão Quente"

    url = f"{API}/{t['number']}"
    r = client.patch(url, json={"client_id": mercado})
    assert r.status_code == 200 and r.json()["client"]["name"] == "Mercado Bom Preço"
    assert eventos(client, t["number"])[-1]["payload"]["changes"]["client"] == {
        "from": {"id": padaria, "name": "Padaria Pão Quente"},
        "to": {"id": mercado, "name": "Mercado Bom Preço"},
    }
    r = client.patch(url, json={"client_id": None})
    assert r.json()["client"] is None
    assert eventos(client, t["number"])[-1]["payload"]["changes"]["client"]["to"] is None

    # Cliente inativo não entra em chamado novo nem numa alteração
    r = client.post(API, json={"title": "Outro", "team_id": cenario["ti"], "client_id": antigo})
    assert r.status_code == 422 and r.json()["detail"] == "Cliente não encontrado ou inativo."
    assert client.patch(url, json={"client_id": antigo}).status_code == 422


# --- comentários, menções e observadores ---------------------------------------------------------


def test_mencao_torna_observador_que_so_comenta(
    client: TestClient, cenario: dict[str, Any]
) -> None:
    t = registrar(client, cenario)
    url = f"{API}/{t['number']}"
    r = client.post(
        f"{url}/comments",
        json={"body": "@Caio consegue olhar a porta 12?", "mention_ids": [cenario["caio"]]},
    )
    assert r.status_code == 201
    assert client.get(url).json()["watchers"] == [
        {"id": cenario["caio"], "full_name": "Caio", "kind": "mentioned"}
    ]

    entrar(client, "caio@x.com")
    detalhe = client.get(url).json()
    assert detalhe["allowed_actions"] == ["comment", "watch_self"]
    assert client.post(f"{url}/comments", json={"body": "Porta ok."}).status_code == 201
    assert client.patch(url, json={"title": "Outro título"}).status_code == 403
    assert client.post(f"{url}/assign", json={"assignee": "me"}).status_code == 403
    assert [c["body"] for c in client.get(f"{url}/comments").json()["items"]] == [
        "@Caio consegue olhar a porta 12?",
        "Porta ok.",
    ]
    # Observador de fora se retira; aí deixa de ver
    assert client.delete(f"{url}/watchers/{cenario['caio']}").status_code == 204
    assert client.get(url).status_code == 403


def test_observadores(client: TestClient, cenario: dict[str, Any]) -> None:
    t = registrar(client, cenario, watcher_ids=[cenario["bia"]])
    url = f"{API}/{t['number']}"
    assert [w["full_name"] for w in t["watchers"]] == ["Bia"]
    assert client.put(f"{url}/watchers/{cenario['caio']}").status_code == 204
    assert [w["full_name"] for w in client.get(url).json()["watchers"]] == ["Bia", "Caio"]
    assert client.put(f"{url}/watchers/{cenario['caio']}").status_code == 204  # já acompanha
    assert client.delete(f"{url}/watchers/{cenario['caio']}").status_code == 204
    assert client.delete(f"{url}/watchers/{cenario['caio']}").status_code == 404
    tipos = [e["type"] for e in eventos(client, t["number"])]
    assert tipos.count("watcher.added") == 2 and tipos.count("watcher.removed") == 1

    # Quem não vê o chamado não consegue se incluir
    entrar(client, "caio@x.com")
    assert client.put(f"{url}/watchers/{cenario['caio']}").status_code == 403


def test_edicao_de_tarefa_pelo_autor_sem_prazo(
    client: TestClient, cenario: dict[str, Any], db: Session
) -> None:
    t = registrar(client, cenario)
    url = f"{API}/{t['number']}/comments"
    c = client.post(url, json={"body": "Primeira versão"}).json()
    assert c["author"]["full_name"] == "Ana"
    assert c["done_at"] == c["created_at"]  # sem data, foi feita agora

    r = client.patch(f"{url}/{c['id']}", json={"body": "Segunda versão"})
    assert r.json()["body"] == "Segunda versão" and r.json()["edited_at"]
    editado = eventos(client, t["number"])[-1]
    assert editado["type"] == "comment.edited"
    assert editado["payload"] == {"comment_id": c["id"], "before": "Primeira versão"}

    assert client.post(url, json={"body": "   "}).status_code == 422
    entrar(client, "bia@x.com")
    r = client.patch(f"{url}/{c['id']}", json={"body": "Da Bia"})
    assert r.status_code == 403 and r.json()["detail"] == "Só o autor altera a tarefa."

    # Sem prazo: dias depois o autor ainda edita
    entrar(client, "ana@x.com")
    db.execute(text("UPDATE ticket_comments SET created_at = now() - interval '3 days'"))
    db.commit()
    assert client.patch(f"{url}/{c['id']}", json={"body": "Tarde"}).status_code == 200


def test_data_da_tarefa_ordena_e_se_corrige(client: TestClient, cenario: dict[str, Any]) -> None:
    t = registrar(client, cenario)
    url = f"{API}/{t['number']}/comments"
    ontem = (datetime.now(UTC) - timedelta(days=1)).replace(microsecond=0)
    hoje = client.post(url, json={"body": "Hoje"}).json()
    antes = client.post(url, json={"body": "Ontem", "done_at": ontem.isoformat()}).json()
    assert datetime.fromisoformat(antes["done_at"]) == ontem
    # A lista segue a data em que a tarefa foi feita, não a do registro
    assert [c["body"] for c in client.get(url).json()["items"]] == ["Ontem", "Hoje"]

    futuro = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    r = client.post(url, json={"body": "Amanhã", "done_at": futuro})
    assert (
        r.status_code == 422 and r.json()["detail"] == "A data da tarefa não pode ficar no futuro."
    )

    dois_dias = ontem - timedelta(days=1)
    r = client.patch(f"{url}/{hoje['id']}", json={"body": "Hoje", "done_at": dois_dias.isoformat()})
    assert datetime.fromisoformat(r.json()["done_at"]) == dois_dias
    anterior = eventos(client, t["number"])[-1]["payload"]["before_done_at"]
    assert datetime.fromisoformat(anterior) == datetime.fromisoformat(hoje["done_at"])
    # Sem done_at, a edição mantém a data
    r = client.patch(f"{url}/{hoje['id']}", json={"body": "Hoje, corrigido"})
    assert datetime.fromisoformat(r.json()["done_at"]) == dois_dias
    assert [c["body"] for c in client.get(url).json()["items"]] == ["Hoje, corrigido", "Ontem"]


def test_remover_tarefa(client: TestClient, cenario: dict[str, Any]) -> None:
    t = registrar(client, cenario, assignee="me")
    url = f"{API}/{t['number']}"
    c = client.post(
        f"{url}/comments", json={"body": "Toner trocado", "time_spent_minutes": 30}
    ).json()
    client.post(f"{url}/comments", json={"body": "Testado", "time_spent_minutes": 15})
    assert client.get(url).json()["time_spent_minutes"] == 45

    entrar(client, "bia@x.com")
    assert client.delete(f"{url}/comments/{c['id']}").status_code == 403  # só o autor
    entrar(client, "ana@x.com")
    assert client.delete(f"{url}/comments/{c['id']}").status_code == 204

    # Sai da lista, do tempo gasto e da busca; o texto fica no histórico
    assert [x["body"] for x in client.get(f"{url}/comments").json()["items"]] == ["Testado"]
    assert client.get(url).json()["time_spent_minutes"] == 15
    assert client.get(API, params={"q": "toner"}).json()["items"] == []
    removido = eventos(client, t["number"])[-1]
    assert removido["type"] == "comment.deleted"
    assert removido["payload"] == {
        "comment_id": c["id"],
        "body": "Toner trocado",
        "time_spent_minutes": 30,
    }
    # Removida não se edita nem se remove de novo
    assert client.delete(f"{url}/comments/{c['id']}").status_code == 404
    r = client.patch(f"{url}/comments/{c['id']}", json={"body": "Volta"})
    assert r.status_code == 404


def test_tempo_gasto_nos_andamentos(client: TestClient, cenario: dict[str, Any]) -> None:
    t = registrar(client, cenario, assignee="me")
    assert t["time_spent_minutes"] == 0 and t["time_by_person"] == []
    url = f"{API}/{t['number']}"
    c = client.post(
        f"{url}/comments", json={"body": "Troquei o toner", "time_spent_minutes": 45}
    ).json()
    assert c["time_spent_minutes"] == 45
    client.post(f"{url}/comments", json={"body": "Pergunta sem tempo"})
    for invalido in (0, -5, 60_001):
        r = client.post(f"{url}/comments", json={"body": "x", "time_spent_minutes": invalido})
        assert r.status_code == 422

    entrar(client, "bia@x.com")
    client.post(f"{url}/comments", json={"body": "Testei a rede", "time_spent_minutes": 90})
    r = client.post(
        f"{url}/transitions",
        json={
            "action": "close",
            "comment": "Resolvido",
            "time_spent_minutes": 15,
            "resolution_code_id": 1,
        },
    )
    assert r.status_code == 200, r.text

    detalhe = client.get(url).json()
    assert detalhe["time_spent_minutes"] == 150
    assert detalhe["time_by_person"] == [
        {"id": cenario["bia"], "full_name": "Bia", "minutes": 105},
        {"id": cenario["ana"], "full_name": "Ana", "minutes": 45},
    ]
    tempos = [x["time_spent_minutes"] for x in client.get(f"{url}/comments").json()["items"]]
    assert tempos == [45, None, 90, 15]

    # A edição muda o tempo (ou o tira), e o tempo anterior fica no histórico
    entrar(client, "ana@x.com")
    r = client.patch(
        f"{url}/comments/{c['id']}", json={"body": "Troquei o toner", "time_spent_minutes": 60}
    )
    assert r.json()["time_spent_minutes"] == 60
    assert eventos(client, t["number"])[-1]["payload"] == {
        "comment_id": c["id"],
        "before": "Troquei o toner",
        "before_time_spent_minutes": 45,
    }
    client.patch(f"{url}/comments/{c['id']}", json={"body": "Troquei o toner"})
    assert client.get(url).json()["time_spent_minutes"] == 105


# --- atribuição e transferência -----------------------------------------------------------------


def test_assumir_atribuir_e_devolver(client: TestClient, cenario: dict[str, Any]) -> None:
    t = registrar(client, cenario)
    url = f"{API}/{t['number']}/assign"
    assert "assign_self" in t["allowed_actions"]

    r = client.post(url, json={"assignee": "me"})
    assert r.json()["assignee"]["full_name"] == "Ana"
    assert client.post(url, json={"assignee": None}).json()["assignee"] is None

    entrar(client, "bia@x.com")
    assert (
        client.post(url, json={"assignee": cenario["ana"]}).json()["assignee"]["full_name"] == "Ana"
    )
    assert client.post(url, json={"assignee": cenario["caio"]}).status_code == 422  # de outro grupo
    atribuicoes = [
        e["payload"] for e in eventos(client, t["number"]) if e["type"] == "ticket.assigned"
    ]
    assert [(a["from"] or {}).get("name") for a in atribuicoes] == [None, "Ana", None]
    assert [(a["to"] or {}).get("name") for a in atribuicoes] == ["Ana", None, "Ana"]


def test_registro_com_varios_responsaveis(client: TestClient, cenario: dict[str, Any]) -> None:
    t = registrar(client, cenario, assignee="me", co_assignee_ids=[cenario["bia"], cenario["ana"]])
    assert t["assignee"]["full_name"] == "Ana"
    assert [u["full_name"] for u in t["co_assignees"]] == ["Bia"]  # o principal não se repete
    criado = eventos(client, t["number"])[0]["payload"]
    assert [u["name"] for u in criado["co_assignees"]] == ["Bia"]

    # Os demais exigem o principal e precisam ser membros ativos do grupo
    sem_principal = {"title": "Sem principal", "category_id": cenario["impressao"]}
    r = client.post(API, json={**sem_principal, "co_assignee_ids": [cenario["bia"]]})
    assert r.status_code == 422
    r = client.post(
        API, json={**sem_principal, "assignee": "me", "co_assignee_ids": [cenario["caio"]]}
    )
    assert r.status_code == 422

    # Para a Bia, o chamado é dela: fila Meus, ações de responsável
    entrar(client, "bia@x.com")
    assert [c["number"] for c in client.get(API, params={"view": "mine"}).json()["items"]] == [
        t["number"]
    ]
    assert [
        c["number"] for c in client.get(API, params={"assignee": cenario["bia"]}).json()["items"]
    ] == [t["number"]]

    # Trocar o principal por um dos demais o tira da lista dos demais
    entrar(client, "ana@x.com")
    url = f"{API}/{t['number']}"
    r = client.post(f"{url}/assign", json={"assignee": cenario["bia"]})
    assert r.json()["assignee"]["full_name"] == "Bia" and r.json()["co_assignees"] == []

    # Devolver à fila tira todos
    t = registrar(client, cenario, assignee="me", co_assignee_ids=[cenario["bia"]])
    url = f"{API}/{t['number']}"
    r = client.post(f"{url}/assign", json={"assignee": None})
    assert r.json()["assignee"] is None and r.json()["co_assignees"] == []
    devolvido = eventos(client, t["number"])[-1]["payload"]
    assert [u["name"] for u in devolvido["co_unassigned"]] == ["Bia"]

    # Transferir também
    t = registrar(client, cenario, assignee="me", co_assignee_ids=[cenario["bia"]])
    url = f"{API}/{t['number']}"
    r = client.post(f"{url}/transfer", json={"team_id": cenario["infra"], "reason": "Rede"})
    assert r.json()["co_assignees"] == []
    transferido = eventos(client, t["number"])[-1]["payload"]
    assert [u["name"] for u in transferido["co_unassigned"]] == ["Bia"]


def test_transferencia(client: TestClient, cenario: dict[str, Any]) -> None:
    t = registrar(client, cenario, assignee="me")
    url = f"{API}/{t['number']}"
    assert (
        client.post(
            f"{url}/transfer", json={"team_id": cenario["infra"], "reason": " "}
        ).status_code
        == 422
    )
    assert (
        client.post(f"{url}/transfer", json={"team_id": cenario["ti"], "reason": "x"}).status_code
        == 422
    )

    r = client.post(f"{url}/transfer", json={"team_id": cenario["infra"], "reason": "É da rede"})
    t = r.json()
    assert t["team"]["name"] == "Infra" and t["assignee"] is None
    assert t["status"]["name"] == "Pendente"
    # O grupo anterior continua vendo, mas não altera mais
    assert t["allowed_actions"] == ["watch_self"]
    assert client.patch(url, json={"title": "Novo"}).status_code == 403
    assert client.get(f"{url}/comments").json()["items"][0]["body"] == "É da rede"
    transferido = eventos(client, t["number"])[-1]
    assert transferido["type"] == "ticket.transferred"
    assert transferido["payload"]["from"]["name"] == "TI"
    assert transferido["payload"]["unassigned"]["name"] == "Ana"

    entrar(client, "caio@x.com")
    assert client.post(f"{url}/assign", json={"assignee": "me"}).status_code == 200


# --- status ------------------------------------------------------------------------------------


def test_ciclo_aguardar_concluir_reabrir(client: TestClient, cenario: dict[str, Any]) -> None:
    t = registrar(client, cenario)
    url = f"{API}/{t['number']}/transitions"

    # Sem responsável, o membro não põe em espera nem conclui (só o responsável ou supervisor)
    assert client.post(url, json={"action": "wait", "comment": "x"}).status_code == 403
    client.post(f"{API}/{t['number']}/assign", json={"assignee": "me"})
    assert client.post(url, json={"action": "wait"}).status_code == 422
    r = client.post(url, json={"action": "wait", "comment": "Aguardando o fornecedor"})
    assert r.json()["status"]["kind"] == "waiting"
    assert "resume" in r.json()["allowed_actions"]
    assert (
        client.post(
            url, json={"action": "close", "comment": "x", "resolution_code_id": 1}
        ).status_code
        == 403
    )

    # O tempo gasto vai no comentário: sem comentário, não há onde lançá-lo
    r = client.post(url, json={"action": "resume", "time_spent_minutes": 5})
    assert r.status_code == 422 and r.json()["detail"] == "Escreva o comentário do tempo gasto."
    assert client.post(url, json={"action": "resume"}).json()["status"]["name"] == "Pendente"
    assert (
        client.post(url, json={"action": "close", "comment": "Troquei o toner"}).status_code == 422
    )
    r = client.post(
        url, json={"action": "close", "comment": "Troquei o toner", "resolution_code_id": 1}
    )
    t = r.json()
    assert t["status"]["name"] == "Concluído" and t["closed_at"]
    assert t["resolution_code"] == {"id": 1, "name": "Feito"}
    solucao = client.get(f"{API}/{t['number']}/comments").json()["items"][-1]
    assert solucao["is_solution"] is True and solucao["body"] == "Troquei o toner"

    entrar(client, "bia@x.com")
    assert client.post(url, json={"action": "reopen"}).status_code == 422
    t = client.post(url, json={"action": "reopen", "comment": "Voltou a falhar"}).json()
    assert t["status"]["name"] == "Pendente" and t["reopened_count"] == 1
    assert t["assignee"]["full_name"] == "Ana"  # volta para o mesmo responsável
    assert t["resolution_code"] is None and t["closed_at"] is None
    mudancas = [
        e["payload"]["action"]
        for e in eventos(client, t["number"])
        if e["type"] == "ticket.status_changed"
    ]
    assert mudancas == ["wait", "resume", "close", "reopen"]


def test_cancelar_pelo_registrante(client: TestClient, cenario: dict[str, Any]) -> None:
    entrar(client, "bia@x.com")
    t = registrar(client, cenario, assignee=cenario["ana"])
    url = f"{API}/{t['number']}/transitions"
    entrar(client, "ana@x.com")
    assert client.post(url, json={"action": "cancel"}).status_code == 422
    t = client.post(url, json={"action": "cancel", "comment": "Era duplicado"}).json()
    assert t["status"]["kind"] == "canceled"
    assert not {"reopen", "close", "assign_self", "transfer"} & set(t["allowed_actions"])
    assert client.post(url, json={"action": "reopen", "comment": "x"}).status_code == 403


# --- lista ------------------------------------------------------------------------------------


def test_lista_filtra_e_pagina_na_ordem_padrao(client: TestClient, cenario: dict[str, Any]) -> None:
    baixa = registrar(client, cenario, title="Baixa")
    critica = registrar(client, cenario, title="Crítica", assignee="me")
    media = registrar(client, cenario, title="Média")
    baixa2 = registrar(client, cenario, title="Baixa 2")

    pagina = client.get(API, params={"limit": 2}).json()
    assert [t["title"] for t in pagina["items"]] == ["Baixa", "Crítica"]
    resto = client.get(API, params={"limit": 2, "cursor": pagina["next_cursor"]}).json()
    assert [t["title"] for t in resto["items"]] == ["Média", "Baixa 2"]
    assert resto["next_cursor"] is None

    def titulos(**params: Any) -> list[str]:
        return [t["title"] for t in client.get(API, params=params).json()["items"]]

    assert titulos(assignee="me") == ["Crítica"]
    assert titulos(assignee="none") == ["Baixa", "Média", "Baixa 2"]
    assert titulos(team=cenario["infra"]) == []
    client.post(f"{API}/{critica['number']}/transitions", json={"action": "wait", "comment": "x"})
    assert titulos(status=["waiting"]) == ["Crítica"]
    assert titulos(status=["open", "closed"]) == ["Baixa", "Média", "Baixa 2"]
    assert client.get(API, params={"cursor": "lixo"}).status_code == 422
    assert client.get(API, params={"assignee": "lixo"}).status_code == 422
    assert {baixa["number"], media["number"], baixa2["number"]}

    entrar(client, "auditor@x.com")
    assert len(titulos()) == 4
