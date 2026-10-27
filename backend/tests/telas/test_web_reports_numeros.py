"""Os números dos relatórios fixados (DES-06): cada bloco de cada modelo pronto, com e sem
"Comparar", com o filtro de pessoa e como supervisora, mais as listas do detalhar e a API. As
mudanças de desempenho (`service.facts` sob demanda, consultas juntas, somas no SQL) não podem
mudar nenhum deles.

Cenário: a semana passada (S, de segunda a domingo) e a anterior (A), com as horas do
expediente padrão (seg. a sex., 8h às 18h).

- Servidor parado (TI, Ana, Padaria): registrado na sex. de A; Aguardando na seg. de S, de volta
  na ter., concluído na qua. Tarefas da Ana: 90 min na seg. às 19h (60 fora), 45 min na ter.
- Rede lenta (TI, Ana e Bia, Cliente Padrão): registrado na ter. de S; Aguardando na qui., de volta
  depois de S. Bia 60 min na qui.; Ana 30 min na sex. às 20h (30 fora).
- Cabo rompido (Infra, Caio, Padaria): registrado na ter. de A, cancelado na sex. de S. Caio 120
  min na qua. de A; 30 min na qua. de S às 7h (30 fora).
- Toner (TI, Ana, Cliente Padrão): registrado na qui. de A, concluído no sáb. de A, reaberto na
  ter. de S e concluído na sex. de S. Ana 60 min no sáb. de A (60 fora); 15 min na sex. de S.
- Backup antigo (TI, Bia, sem cliente): registrado 20 dias antes de S, em aberto. Bia 40 min na
  qua. de S às 9h40 (dentro do expediente).
- Impressora nova (Infra, Caio, Cliente Padrão): registrado no sáb. de S, em aberto. Caio 45 min
  no sáb. (45 fora).

E mais: a Bia também é responsável pelo Toner; a Ana tem 150 min no Servidor parado terminando
à 0h30 da qua. de S (atravessa a meia-noite); a qui. de S é feriado (a tarefa da Bia na Rede
lenta fica toda fora do expediente).
"""

import re
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from chamados.modules.identity.models import User
from chamados.modules.system.models import SystemSetting
from chamados.modules.tickets.models import Ticket, TicketCoAssignee, TicketEvent
from chamados.web import reports
from chamados.web.reports_blocks import block_view
from tests.apoio import API, dia_util_passado, em, registrar, tarefa
from tests.conftest import criar_cliente, entrar, outra_sessao


def _acao(client: TestClient, numero: int, acao: str, **extra: Any) -> None:
    r = client.post(f"{API}/{numero}/transitions", json={"action": acao, **extra})
    assert r.status_code == 200, r.text


def _datas(db: Session, numero: int, **valores: Any) -> None:
    db.execute(update(Ticket).where(Ticket.number == numero).values(**valores))


def _mudancas(db: Session, numero: int, *quando: datetime) -> None:
    """As datas das mudanças de status do chamado, na ordem em que foram feitas."""
    ticket_id = db.scalar(select(Ticket.id).where(Ticket.number == numero))
    ids = db.scalars(
        select(TicketEvent.id)
        .where(
            TicketEvent.ticket_id == ticket_id,
            TicketEvent.event_type == "ticket.status_changed",
        )
        .order_by(TicketEvent.id)
    ).all()
    assert len(ids) == len(quando)
    # O histórico é append-only (trigger): a data muda com a trigger desligada.
    db.connection().exec_driver_sql("ALTER TABLE ticket_events DISABLE TRIGGER USER")
    for event_id, momento in zip(ids, quando, strict=True):
        db.execute(update(TicketEvent).where(TicketEvent.id == event_id).values(created_at=momento))
    db.connection().exec_driver_sql("ALTER TABLE ticket_events ENABLE TRIGGER USER")


@pytest.fixture
def semana(client: TestClient, cenario: dict[str, Any], db: Session) -> date:
    """Monta o cenário da docstring e devolve a segunda-feira de S."""
    seg = dia_util_passado()
    padaria = criar_cliente(db, "Padaria Pão Quente", "11222333000181")
    bia, caio = outra_sessao(client), outra_sessao(client)
    entrar(bia, "bia@x.com")
    entrar(caio, "caio@x.com")
    fechar = {"comment": "Pronto", "resolution_code_id": 1}

    servidor = registrar(client, cenario, client_id=padaria, title="Servidor parado")["number"]
    tarefa(client, servidor, 90, em(seg, 19))
    tarefa(client, servidor, 45, em(seg + timedelta(days=1), 10))
    _acao(client, servidor, "wait", comment="Esperando o cliente")
    _acao(client, servidor, "resume")
    _acao(client, servidor, "close", **fechar)

    rede = registrar(client, cenario, title="Rede lenta", co_assignee_ids=[cenario["bia"]])
    rede_n = rede["number"]
    tarefa(bia, rede_n, 60, em(seg + timedelta(days=3), 11))
    tarefa(client, rede_n, 30, em(seg + timedelta(days=4), 20))
    _acao(client, rede_n, "wait", comment="Esperando o cliente")
    _acao(client, rede_n, "resume")

    infra = {"team_id": cenario["infra"], "category_id": None}
    cabo = registrar(caio, cenario, client_id=padaria, title="Cabo rompido", **infra)["number"]
    tarefa(caio, cabo, 120, em(seg - timedelta(days=5), 10))
    tarefa(caio, cabo, 30, em(seg + timedelta(days=2), 7))
    _acao(caio, cabo, "cancel")

    toner = registrar(client, cenario, title="Toner")["number"]
    tarefa(client, toner, 60, em(seg - timedelta(days=2), 16))
    tarefa(client, toner, 15, em(seg + timedelta(days=4), 15, 30))
    _acao(client, toner, "close", **fechar)
    _acao(client, toner, "reopen", comment="Voltou a falhar")
    _acao(client, toner, "close", **fechar)

    backup = registrar(bia, cenario, title="Backup antigo")["number"]
    impressora = registrar(caio, cenario, title="Impressora nova", **infra)["number"]
    tarefa(caio, impressora, 45, em(seg + timedelta(days=5), 10))
    tarefa(bia, backup, 40, em(seg + timedelta(days=2), 9, 40))
    tarefa(client, servidor, 150, em(seg + timedelta(days=2), 0, 30))

    _datas(db, servidor, created_at=em(seg - timedelta(days=3), 9))
    _mudancas(
        db, servidor, em(seg, 10), em(seg + timedelta(days=1), 10), em(seg + timedelta(days=2), 15)
    )
    _datas(db, servidor, closed_at=em(seg + timedelta(days=2), 15))
    _datas(db, rede_n, created_at=em(seg + timedelta(days=1), 8))
    _mudancas(db, rede_n, em(seg + timedelta(days=3), 10), em(seg + timedelta(days=8), 10))
    _datas(
        db,
        cabo,
        created_at=em(seg - timedelta(days=6), 9),
        canceled_at=em(seg + timedelta(days=4), 12),
    )
    _mudancas(db, cabo, em(seg + timedelta(days=4), 12))
    _datas(db, toner, created_at=em(seg - timedelta(days=4), 9))
    _mudancas(
        db,
        toner,
        em(seg - timedelta(days=2), 17),
        em(seg + timedelta(days=1), 9),
        em(seg + timedelta(days=4), 16),
    )
    _datas(db, toner, closed_at=em(seg + timedelta(days=4), 16))
    _datas(db, backup, created_at=em(seg - timedelta(days=20), 9), client_id=None)
    _datas(db, impressora, created_at=em(seg + timedelta(days=5), 10))
    toner_id = db.scalar(select(Ticket.id).where(Ticket.number == toner))
    bia_id = db.scalar(select(User.id).where(User.email == "bia@x.com"))
    db.add(TicketCoAssignee(ticket_id=toner_id, user_id=bia_id))
    feriado = (seg + timedelta(days=3)).isoformat()
    expediente = {"weekdays": [0, 1, 2, 3, 4], "start": "08:00", "end": "18:00"}
    db.add(SystemSetting(key="work_hours", value={**expediente, "holidays": [feriado]}))
    db.commit()
    return seg


def _resumo(view: dict[str, Any], inicio: date) -> list[str]:
    """Um bloco da tela em texto: os períodos pelo dia em relação ao início (d0, d7…)."""
    visual = view["visual"]
    linhas = [f"{visual}: {view['title']}"]
    if visual == "cards":
        for card in view["cards"]:
            texto = f"{card['label']}={card['value']}"
            if "before" in card:
                texto += f" ({card['change'] or '·'}; antes {card['before']})"
            linhas.append(texto)
    elif "points" in view:
        for p in view["points"]:
            chave = p.key
            try:
                chave = f"d{(date.fromisoformat(p.key) - inicio).days}"
            except ValueError:
                chave = p.label
            antes = f" antes {p.before}" if p.before is not None else ""
            linhas.append(f"{chave}={p.value}+{p.extra}{antes}")
    elif visual == "table":
        for rotulo, _, celulas in view["rows"]:
            linhas.append(f"{rotulo}: " + " | ".join(t for t, _ in celulas))
        linhas.append("Total: " + " | ".join(t for t, _ in view["total"]))
    else:
        linhas.append(f"{view['count']} tarefas")
        linhas += [f"{t['title']} {t['minutes']} {t['overtime']}" for t in view["tasks"]]
    return linhas


def _blocos(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, inicio: date, **filtros: Any
) -> list[str]:
    """Os blocos que a tela calculou, resumidos."""
    vistos: list[dict[str, Any]] = []
    original = block_view

    def guardar(*args: Any, **kwargs: Any) -> dict[str, Any]:
        view = original(*args, **kwargs)
        vistos.append(view)
        return view

    monkeypatch.setattr(reports, "block_view", guardar)
    fim = inicio + timedelta(days=6)
    r = client.get(
        "/relatorios/blocos",
        params={
            "periodo": "personalizado",
            "de": inicio.isoformat(),
            "ate": fim.isoformat(),
            **filtros,
        },
    )
    assert r.status_code == 200, r.text
    monkeypatch.setattr(reports, "block_view", original)
    return [linha for v in vistos for linha in _resumo(v, inicio)]


def _linhas(html: str) -> list[str]:
    """As linhas da lista de chamados do detalhar, sem o número nem as datas (que mudam)."""
    linhas = []
    for linha in re.findall(r'<tr class="border-t border-border">(.*?)</tr>', html, re.S):
        celulas = [
            re.sub(r"<[^>]+>|#\d+", "", c).strip()
            for c in re.findall(r"<td[^>]*>(.*?)</td>", linha, re.S)
        ]
        linhas.append(" | ".join(c for c in celulas if not re.match(r"\d{2}/\d{2}/\d{4}", c)))
    return linhas


MODELOS = ("produtividade", "clientes", "horas-extras", "chamados")


def test_numeros_dos_modelos_prontos(
    client: TestClient,
    cenario: dict[str, Any],
    db: Session,
    semana: date,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auditor = outra_sessao(client)
    entrar(auditor, "auditor@x.com")
    bia = outra_sessao(client)
    entrar(bia, "bia@x.com")
    vistos = {}
    for aba in MODELOS:
        vistos[f"{aba} · tudo"] = _blocos(auditor, monkeypatch, semana, aba=aba)
        vistos[f"{aba} · tudo, comparar"] = _blocos(
            auditor, monkeypatch, semana, aba=aba, comparar="1"
        )
        vistos[f"{aba} · Ana, comparar"] = _blocos(
            auditor, monkeypatch, semana, aba=aba, comparar="1", pessoa=cenario["ana"]
        )
        vistos[f"{aba} · supervisora, comparar"] = _blocos(
            bia, monkeypatch, semana, aba=aba, comparar="1"
        )
    # A aba Clientes com a hora extra separada: no expediente e extras ao lado das horas.
    vistos["clientes · separada, comparar"] = _blocos(
        auditor, monkeypatch, semana, aba="clientes", comparar="1", extras="separada"
    )
    assert vistos == ESPERADO


def test_listas_do_detalhar_e_api(
    client: TestClient, cenario: dict[str, Any], semana: date
) -> None:
    auditor = outra_sessao(client)
    entrar(auditor, "auditor@x.com")
    bia = outra_sessao(client)
    entrar(bia, "bia@x.com")
    fim = semana + timedelta(days=6)
    tela = {"periodo": "personalizado", "de": semana.isoformat(), "ate": fim.isoformat()}
    api = {"start": semana.isoformat(), "end": fim.isoformat()}
    vistos: dict[str, Any] = {}
    for quem, sessao in (("tudo", auditor), ("supervisora", bia)):
        for medida in ("opened", "closed", "canceled", "backlog", "lead_time"):
            r = sessao.get("/relatorios/chamados", params={**tela, "medida": medida})
            vistos[f"{quem} · {medida}"] = _linhas(r.text)
        dados = sessao.get("/api/v1/reports", params=api).json()
        vistos[f"{quem} · api"] = {
            "totals": dados["totals"],
            "people": [
                (p["name"], p["minutes"], p["overtime_minutes"], p["tasks"], p["tickets_closed"])
                for p in dados["people"]
            ],
            "clients": [
                (c["name"], c["minutes"], c["tickets_opened"], c["tickets_closed"])
                for c in dados["clients"]
            ],
            "overtime": [
                (t["ticket_title"], t["minutes"], t["overtime_minutes"])
                for t in dados["overtime_tasks"]
            ],
        }
    assert vistos == LISTAS


ESPERADO: dict[str, list[str]] = {
    "produtividade · tudo": [
        "cards: ",
        "Horas=8h25",
        "Horas extras=6h15",
        "Tarefas=9",
        "Chamados registrados=2",
        "Chamados concluídos=2",
        "columns: Horas por dia",
        "d0=90+0",
        "d1=45+0",
        "d2=220+0",
        "d3=60+0",
        "d4=45+0",
        "d5=45+0",
        "d6=0+0",
        "bars: Horas por pessoa",
        "Ana=330+0",
        "Bia=100+0",
        "Caio=75+0",
        "table: Por pessoa",
        "Ana: 5h30 | 4h | 5 | 2",
        "Bia: 1h40 | 1h | 2 | 1",
        "Caio: 1h15 | 1h15 | 2 | 0",
        "Total: 8h25 | 6h15 | 9 | 2",
    ],
    "produtividade · tudo, comparar": [
        "cards: ",
        "Horas=8h25 (+181%; antes 3h)",
        "Horas extras=6h15 (+525%; antes 1h)",
        "Tarefas=9 (+350%; antes 2)",
        "Chamados registrados=2 (−33%; antes 3)",
        "Chamados concluídos=2 (·; antes 0)",
        "columns: Horas por dia",
        "d0=90+0 antes 0",
        "d1=45+0 antes 0",
        "d2=220+0 antes 120",
        "d3=60+0 antes 0",
        "d4=45+0 antes 0",
        "d5=45+0 antes 60",
        "d6=0+0 antes 0",
        "bars: Horas por pessoa",
        "Ana=330+0",
        "Bia=100+0",
        "Caio=75+0",
        "table: Por pessoa",
        "Ana: 5h30 | +450% | 4h | +300% | 5 | +400% | 2 | ",
        "Bia: 1h40 |  | 1h |  | 2 |  | 1 | ",
        "Caio: 1h15 | −38% | 1h15 |  | 2 | +100% | 0 | ",
        "Total: 8h25 | +181% | 6h15 | +525% | 9 | +350% | 2 | ",
    ],
    "produtividade · Ana, comparar": [
        "cards: ",
        "Horas=5h30 (+450%; antes 1h)",
        "Horas extras=4h (+300%; antes 1h)",
        "Tarefas=5 (+400%; antes 1)",
        "Chamados registrados=1 (−50%; antes 2)",
        "Chamados concluídos=2 (·; antes 0)",
        "columns: Horas por dia",
        "d0=90+0 antes 0",
        "d1=45+0 antes 0",
        "d2=150+0 antes 0",
        "d3=0+0 antes 0",
        "d4=45+0 antes 0",
        "d5=0+0 antes 60",
        "d6=0+0 antes 0",
        "bars: Horas por pessoa",
        "Ana=330+0",
        "table: Por pessoa",
        "Ana: 5h30 | +450% | 4h | +300% | 5 | +400% | 2 | ",
        "Total: 5h30 | +450% | 4h | +300% | 5 | +400% | 2 | ",
    ],
    "produtividade · supervisora, comparar": [
        "cards: ",
        "Horas=7h10 (+617%; antes 1h)",
        "Horas extras=5h (+400%; antes 1h)",
        "Tarefas=7 (+600%; antes 1)",
        "Chamados registrados=1 (−50%; antes 2)",
        "Chamados concluídos=2 (·; antes 0)",
        "columns: Horas por dia",
        "d0=90+0 antes 0",
        "d1=45+0 antes 0",
        "d2=190+0 antes 0",
        "d3=60+0 antes 0",
        "d4=45+0 antes 0",
        "d5=0+0 antes 60",
        "d6=0+0 antes 0",
        "bars: Horas por pessoa",
        "Ana=330+0",
        "Bia=100+0",
        "table: Por pessoa",
        "Ana: 5h30 | +450% | 4h | +300% | 5 | +400% | 2 | ",
        "Bia: 1h40 |  | 1h |  | 2 |  | 1 | ",
        "Total: 7h10 | +617% | 5h | +400% | 7 | +600% | 2 | ",
    ],
    "clientes · tudo": [
        "cards: ",
        "Horas=8h25",
        "Tarefas=9",
        "Chamados registrados=2",
        "Chamados concluídos=2",
        "bars: Horas por cliente (os 10 maiores)",
        "Padaria Pão Quente=315+0",
        "Cliente Padrão=150+0",
        "Sem cliente=40+0",
        "table: Por cliente",
        "Padaria Pão Quente: 5h15 | 0 | 1",
        "Cliente Padrão: 2h30 | 2 | 1",
        "Sem cliente: 40min | 0 | 0",
        "Total: 8h25 | 2 | 2",
    ],
    "clientes · tudo, comparar": [
        "cards: ",
        "Horas=8h25 (+181%; antes 3h)",
        "Tarefas=9 (+350%; antes 2)",
        "Chamados registrados=2 (−33%; antes 3)",
        "Chamados concluídos=2 (·; antes 0)",
        "bars: Horas por cliente (os 10 maiores)",
        "Padaria Pão Quente=315+0",
        "Cliente Padrão=150+0",
        "Sem cliente=40+0",
        "table: Por cliente",
        "Padaria Pão Quente: 5h15 | +162% | 0 | −100% | 1 | ",
        "Cliente Padrão: 2h30 | +150% | 2 | +100% | 1 | ",
        "Sem cliente: 40min |  | 0 |  | 0 | ",
        "Total: 8h25 | +181% | 2 | −33% | 2 | ",
    ],
    "clientes · Ana, comparar": [
        "cards: ",
        "Horas=5h30 (+450%; antes 1h)",
        "Tarefas=5 (+400%; antes 1)",
        "Chamados registrados=1 (−50%; antes 2)",
        "Chamados concluídos=2 (·; antes 0)",
        "bars: Horas por cliente (os 10 maiores)",
        "Padaria Pão Quente=285+0",
        "Cliente Padrão=45+0",
        "table: Por cliente",
        "Padaria Pão Quente: 4h45 |  | 0 | −100% | 1 | ",
        "Cliente Padrão: 45min | −25% | 1 | 0% | 1 | ",
        "Total: 5h30 | +450% | 1 | −50% | 2 | ",
    ],
    "clientes · supervisora, comparar": [
        "cards: ",
        "Horas=7h10 (+617%; antes 1h)",
        "Tarefas=7 (+600%; antes 1)",
        "Chamados registrados=1 (−50%; antes 2)",
        "Chamados concluídos=2 (·; antes 0)",
        "bars: Horas por cliente (os 10 maiores)",
        "Padaria Pão Quente=285+0",
        "Cliente Padrão=105+0",
        "Sem cliente=40+0",
        "table: Por cliente",
        "Padaria Pão Quente: 4h45 |  | 0 | −100% | 1 | ",
        "Cliente Padrão: 1h45 | +75% | 1 | 0% | 1 | ",
        "Sem cliente: 40min |  | 0 |  | 0 | ",
        "Total: 7h10 | +617% | 1 | −50% | 2 | ",
    ],
    # No expediente + extras = horas, em cada linha e no total.
    "clientes · separada, comparar": [
        "cards: ",
        "Horas=8h25 (+181%; antes 3h)",
        "Horas no expediente=2h10 (+8%; antes 2h)",
        "Horas extras=6h15 (+525%; antes 1h)",
        "Tarefas=9 (+350%; antes 2)",
        "Chamados registrados=2 (−33%; antes 3)",
        "Chamados concluídos=2 (·; antes 0)",
        "bars: Horas por cliente (os 10 maiores)",
        "Padaria Pão Quente=315+0",
        "Cliente Padrão=150+0",
        "Sem cliente=40+0",
        "table: Por cliente",
        "Padaria Pão Quente: 5h15 | +162% | 1h15 | −38% | 4h |  | 0 | −100% | 1 | ",
        "Cliente Padrão: 2h30 | +150% | 15min |  | 2h15 | +125% | 2 | +100% | 1 | ",
        "Sem cliente: 40min |  | 40min |  | 0min |  | 0 |  | 0 | ",
        "Total: 8h25 | +181% | 2h10 | +8% | 6h15 | +525% | 2 | −33% | 2 | ",
    ],
    "horas-extras · tudo": [
        "cards: ",
        "Horas=8h25",
        "Horas extras=6h15",
        "Tarefas=9",
        "Chamados registrados=2",
        "Chamados concluídos=2",
        "columns: Horas extras por dia",
        "d0=60+0",
        "d1=0+0",
        "d2=180+0",
        "d3=60+0",
        "d4=30+0",
        "d5=45+0",
        "d6=0+0",
        "bars: Horas extras por pessoa",
        "Ana=240+0",
        "Caio=75+0",
        "Bia=60+0",
        "tasks: Tarefas fora do expediente",
        "6 tarefas",
        "Servidor parado 1h30 1h",
        "Servidor parado 2h30 2h30",
        "Cabo rompido 30min 30min",
        "Rede lenta 1h 1h",
        "Rede lenta 30min 30min",
        "Impressora nova 45min 45min",
    ],
    "horas-extras · tudo, comparar": [
        "cards: ",
        "Horas=8h25 (+181%; antes 3h)",
        "Horas extras=6h15 (+525%; antes 1h)",
        "Tarefas=9 (+350%; antes 2)",
        "Chamados registrados=2 (−33%; antes 3)",
        "Chamados concluídos=2 (·; antes 0)",
        "columns: Horas extras por dia",
        "d0=60+0 antes 0",
        "d1=0+0 antes 0",
        "d2=180+0 antes 0",
        "d3=60+0 antes 0",
        "d4=30+0 antes 0",
        "d5=45+0 antes 60",
        "d6=0+0 antes 0",
        "bars: Horas extras por pessoa",
        "Ana=240+0",
        "Caio=75+0",
        "Bia=60+0",
        "tasks: Tarefas fora do expediente",
        "6 tarefas",
        "Servidor parado 1h30 1h",
        "Servidor parado 2h30 2h30",
        "Cabo rompido 30min 30min",
        "Rede lenta 1h 1h",
        "Rede lenta 30min 30min",
        "Impressora nova 45min 45min",
    ],
    "horas-extras · Ana, comparar": [
        "cards: ",
        "Horas=5h30 (+450%; antes 1h)",
        "Horas extras=4h (+300%; antes 1h)",
        "Tarefas=5 (+400%; antes 1)",
        "Chamados registrados=1 (−50%; antes 2)",
        "Chamados concluídos=2 (·; antes 0)",
        "columns: Horas extras por dia",
        "d0=60+0 antes 0",
        "d1=0+0 antes 0",
        "d2=150+0 antes 0",
        "d3=0+0 antes 0",
        "d4=30+0 antes 0",
        "d5=0+0 antes 60",
        "d6=0+0 antes 0",
        "bars: Horas extras por pessoa",
        "Ana=240+0",
        "tasks: Tarefas fora do expediente",
        "3 tarefas",
        "Servidor parado 1h30 1h",
        "Servidor parado 2h30 2h30",
        "Rede lenta 30min 30min",
    ],
    "horas-extras · supervisora, comparar": [
        "cards: ",
        "Horas=7h10 (+617%; antes 1h)",
        "Horas extras=5h (+400%; antes 1h)",
        "Tarefas=7 (+600%; antes 1)",
        "Chamados registrados=1 (−50%; antes 2)",
        "Chamados concluídos=2 (·; antes 0)",
        "columns: Horas extras por dia",
        "d0=60+0 antes 0",
        "d1=0+0 antes 0",
        "d2=150+0 antes 0",
        "d3=60+0 antes 0",
        "d4=30+0 antes 0",
        "d5=0+0 antes 60",
        "d6=0+0 antes 0",
        "bars: Horas extras por pessoa",
        "Ana=240+0",
        "Bia=60+0",
        "tasks: Tarefas fora do expediente",
        "4 tarefas",
        "Servidor parado 1h30 1h",
        "Servidor parado 2h30 2h30",
        "Rede lenta 1h 1h",
        "Rede lenta 30min 30min",
    ],
    "chamados · tudo": [
        "cards: ",
        "Chamados registrados=2",
        "Chamados concluídos=2",
        "Chamados cancelados=1",
        "Em aberto no fim=3",
        "cards: ",
        "Mediana até a conclusão=6d 18h",
        "Mediana até a conclusão (líquida)=4d 22h",
        "Reabertura=50%",
        "line: Chamados registrados por semana",
        "d0=2+0",
        "line: Chamados concluídos por semana",
        "d0=2+0",
        "columns: Em aberto no fim por idade",
        "até 1 dia=0+0",
        "1 a 3 dias=1+0",
        "3 a 7 dias=1+0",
        "mais de 7 dias=1+0",
        "bars: Em aberto no fim por status",
        "Pendente=2+0",
        "Aguardando cliente=1+0",
        "table: Por grupo",
        "Infra: 1 | 0 | 1 | 1 | — | —",
        "TI: 1 | 2 | 0 | 2 | 6d 18h | 50%",
        "Total: 2 | 2 | 1 | 3 | 6d 18h | 50%",
    ],
    "chamados · tudo, comparar": [
        "cards: ",
        "Chamados registrados=2 (−33%; antes 3)",
        "Chamados concluídos=2 (·; antes 0)",
        "Chamados cancelados=1 (·; antes 0)",
        "Em aberto no fim=3 (0%; antes 3)",
        "cards: ",
        "Mediana até a conclusão=6d 18h (·; antes —)",
        "Mediana até a conclusão (líquida)=4d 22h (·; antes —)",
        "Reabertura=50% (·; antes —)",
        "line: Chamados registrados por semana",
        "d0=2+0 antes 3",
        "line: Chamados concluídos por semana",
        "d0=2+0 antes 0",
        "columns: Em aberto no fim por idade",
        "até 1 dia=0+0",
        "1 a 3 dias=1+0",
        "3 a 7 dias=1+0",
        "mais de 7 dias=1+0",
        "bars: Em aberto no fim por status",
        "Pendente=2+0",
        "Aguardando cliente=1+0",
        "table: Por grupo",
        "Infra: 1 | 0% | 0 |  | 1 |  | 1 | 0% | — |  | — | ",
        "TI: 1 | −50% | 2 |  | 0 |  | 2 | 0% | 6d 18h |  | 50% | ",
        "Total: 2 | −33% | 2 |  | 1 |  | 3 | 0% | 6d 18h |  | 50% | ",
    ],
    "chamados · Ana, comparar": [
        "cards: ",
        "Chamados registrados=1 (−50%; antes 2)",
        "Chamados concluídos=2 (·; antes 0)",
        "Chamados cancelados=0 (·; antes 0)",
        "Em aberto no fim=1 (0%; antes 1)",
        "cards: ",
        "Mediana até a conclusão=6d 18h (·; antes —)",
        "Mediana até a conclusão (líquida)=4d 22h (·; antes —)",
        "Reabertura=50% (·; antes —)",
        "line: Chamados registrados por semana",
        "d0=1+0 antes 2",
        "line: Chamados concluídos por semana",
        "d0=2+0 antes 0",
        "columns: Em aberto no fim por idade",
        "até 1 dia=0+0",
        "1 a 3 dias=0+0",
        "3 a 7 dias=1+0",
        "mais de 7 dias=0+0",
        "bars: Em aberto no fim por status",
        "Aguardando cliente=1+0",
        "table: Por grupo",
        "TI: 1 | −50% | 2 |  | 0 |  | 1 | 0% | 6d 18h |  | 50% | ",
        "Total: 1 | −50% | 2 |  | 0 |  | 1 | 0% | 6d 18h |  | 50% | ",
    ],
    "chamados · supervisora, comparar": [
        "cards: ",
        "Chamados registrados=1 (−50%; antes 2)",
        "Chamados concluídos=2 (·; antes 0)",
        "Chamados cancelados=0 (·; antes 0)",
        "Em aberto no fim=2 (0%; antes 2)",
        "cards: ",
        "Mediana até a conclusão=6d 18h (·; antes —)",
        "Mediana até a conclusão (líquida)=4d 22h (·; antes —)",
        "Reabertura=50% (·; antes —)",
        "line: Chamados registrados por semana",
        "d0=1+0 antes 2",
        "line: Chamados concluídos por semana",
        "d0=2+0 antes 0",
        "columns: Em aberto no fim por idade",
        "até 1 dia=0+0",
        "1 a 3 dias=0+0",
        "3 a 7 dias=1+0",
        "mais de 7 dias=1+0",
        "bars: Em aberto no fim por status",
        "Aguardando cliente=1+0",
        "Pendente=1+0",
        "table: Por grupo",
        "TI: 1 | −50% | 2 |  | 0 |  | 2 | 0% | 6d 18h |  | 50% | ",
        "Total: 1 | −50% | 2 |  | 0 |  | 2 | 0% | 6d 18h |  | 50% | ",
    ],
}
LISTAS: dict[str, Any] = {
    "tudo · opened": [
        "Impressora nova | Cliente Padrão | Infra | Pendente | Caio",
        "Rede lenta | Cliente Padrão | TI | Pendente | Ana, Bia",
    ],
    "tudo · closed": [
        "Toner | Cliente Padrão | TI | Concluído | Ana, Bia | 8d 7h | 5d 15h | Sim",
        "Servidor parado | Padaria Pão Quente | TI | Concluído | Ana | 5d 6h | 4d 6h | Não",
    ],
    "tudo · canceled": ["Cabo rompido | Padaria Pão Quente | Infra | Cancelado | Caio"],
    "tudo · backlog": [
        "Backup antigo | Sem cliente | TI | Pendente | Bia | 26d 15h",
        "Rede lenta | Cliente Padrão | TI | Aguardando cliente | Ana, Bia | 5d 16h",
        "Impressora nova | Cliente Padrão | Infra | Pendente | Caio | 1d 14h",
    ],
    "tudo · lead_time": [
        "Toner | Cliente Padrão | TI | Concluído | Ana, Bia | 8d 7h | 5d 15h | Sim",
        "Servidor parado | Padaria Pão Quente | TI | Concluído | Ana | 5d 6h | 4d 6h | Não",
    ],
    "tudo · api": {
        "totals": {
            "minutes": 505,
            "overtime_minutes": 375,
            "tasks": 9,
            "tickets_opened": 2,
            "tickets_closed": 2,
        },
        "people": [("Ana", 330, 240, 5, 2), ("Bia", 100, 60, 2, 1), ("Caio", 75, 75, 2, 0)],
        "clients": [
            ("Padaria Pão Quente", 315, 0, 1),
            ("Cliente Padrão", 150, 2, 1),
            (None, 40, 0, 0),
        ],
        "overtime": [
            ("Servidor parado", 90, 60),
            ("Servidor parado", 150, 150),
            ("Cabo rompido", 30, 30),
            ("Rede lenta", 60, 60),
            ("Rede lenta", 30, 30),
            ("Impressora nova", 45, 45),
        ],
    },
    "supervisora · opened": ["Rede lenta | Cliente Padrão | TI | Pendente | Ana, Bia"],
    "supervisora · closed": [
        "Toner | Cliente Padrão | TI | Concluído | Ana, Bia | 8d 7h | 5d 15h | Sim",
        "Servidor parado | Padaria Pão Quente | TI | Concluído | Ana | 5d 6h | 4d 6h | Não",
    ],
    "supervisora · canceled": [],
    "supervisora · backlog": [
        "Backup antigo | Sem cliente | TI | Pendente | Bia | 26d 15h",
        "Rede lenta | Cliente Padrão | TI | Aguardando cliente | Ana, Bia | 5d 16h",
    ],
    "supervisora · lead_time": [
        "Toner | Cliente Padrão | TI | Concluído | Ana, Bia | 8d 7h | 5d 15h | Sim",
        "Servidor parado | Padaria Pão Quente | TI | Concluído | Ana | 5d 6h | 4d 6h | Não",
    ],
    "supervisora · api": {
        "totals": {
            "minutes": 430,
            "overtime_minutes": 300,
            "tasks": 7,
            "tickets_opened": 1,
            "tickets_closed": 2,
        },
        "people": [("Ana", 330, 240, 5, 2), ("Bia", 100, 60, 2, 1)],
        "clients": [
            ("Padaria Pão Quente", 285, 0, 1),
            ("Cliente Padrão", 105, 1, 1),
            (None, 40, 0, 0),
        ],
        "overtime": [
            ("Servidor parado", 90, 60),
            ("Servidor parado", 150, 150),
            ("Rede lenta", 60, 60),
            ("Rede lenta", 30, 30),
        ],
    },
}
