"""Painel do papel Cliente (/painel, docs/14 §14.9) e a empresa no cadastro de usuário."""

import uuid
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from chamados.modules.catalog.models import TicketStatus
from chamados.modules.clients.models import Client
from chamados.modules.identity.models import User
from chamados.modules.reports.service import TZ
from chamados.modules.tickets.models import Ticket
from tests.api.test_papel_cliente import usuario_cliente
from tests.apoio import registrar, tarefa
from tests.conftest import criar_cliente, criar_usuario, entrar, outra_sessao


def _contrato(db: Session, cliente: str, tipo: str, horas: int | None) -> None:
    c = db.scalar(select(Client).where(Client.public_id == uuid.UUID(cliente)))
    assert c is not None
    c.contract_type, c.contract_hours = tipo, horas
    db.commit()


def _cliente(client: TestClient, cenario: dict[str, str], db: Session) -> TestClient:
    usuario_cliente(db, cenario["cliente"])
    sessao = outra_sessao(client)
    entrar(sessao, "cli@x.com")
    return sessao


def test_painel_mostra_o_plano_e_os_chamados_da_empresa(
    client: TestClient, cenario: dict[str, str], db: Session
) -> None:
    _contrato(db, cenario["cliente"], "monthly", 2)
    agora = datetime.now(TZ) - timedelta(minutes=1)
    a = registrar(client, cenario, title="Servidor fora do ar")["number"]
    b = registrar(client, cenario, title="Troca de toner")["number"]
    tarefa(client, a, 90, agora)
    tarefa(client, b, 60, agora)
    outra = criar_cliente(db, "Outra", "11222333000181")
    de_outra = registrar(client, cenario, title="De outra", client_id=outra)["number"]
    tarefa(client, de_outra, 30, agora)
    # Concluído no mês passado, sem trabalho neste mês: fica de fora.
    antigo = registrar(client, cenario, title="Antigo")["number"]
    ticket = db.scalar(select(Ticket).where(Ticket.number == antigo))
    assert ticket is not None
    ticket.created_at = agora - timedelta(days=40)
    ticket.status_id = db.scalars(
        select(TicketStatus.id).where(
            TicketStatus.kind == "closed", TicketStatus.is_default_for_kind
        )
    ).one()
    db.commit()

    html = _cliente(client, cenario, db).get("/painel").text
    assert "Cliente Padrão" in html
    assert "por mês" in html
    assert "2h30" in html  # trabalhadas
    assert "30min" in html  # excedentes: além das 2 h do plano
    assert f"#{a} Servidor fora do ar" in html and f"#{b} Troca de toner" in html
    assert "De outra" not in html and "Antigo" not in html
    assert html.index(f"#{a} ") < html.index(f"#{b} ")  # o mais trabalhado primeiro


def test_contrato_anual_mostra_o_ano_e_avulso_fica_sem_plano(
    client: TestClient, cenario: dict[str, str], db: Session
) -> None:
    sessao = _cliente(client, cenario, db)
    _contrato(db, cenario["cliente"], "annual", 100)
    html = sessao.get("/painel").text
    assert f"Horas em {datetime.now(TZ).year}" in html and "por ano" in html
    _contrato(db, cenario["cliente"], "on_demand", None)
    html = sessao.get("/painel").text
    assert "Sem plano" in html and "Horas excedentes" not in html


def test_cliente_so_abre_o_painel(client: TestClient, cenario: dict[str, str], db: Session) -> None:
    sessao = _cliente(client, cenario, db)
    for tela in ("/chamados", "/quadro", "/relatorios", "/admin/usuarios", "/meus-tokens"):
        r = sessao.get(tela, follow_redirects=False)
        assert (r.status_code, r.headers["location"]) == (303, "/painel"), tela
    html = sessao.get("/painel").text
    assert 'href="/painel"' in html
    assert 'href="/chamados"' not in html and 'href="/meus-tokens"' not in html
    # Quem não é Cliente não tem painel.
    assert client.get("/painel").status_code == 403


def test_cadastro_de_usuario_com_o_papel_cliente(client: TestClient, db: Session) -> None:
    criar_usuario(db, "admin@x.com", "admin", nome="Admin")
    entrar(client, "admin@x.com")
    acme = criar_cliente(db, "Acme", "33445566000186", ativo=False)
    html = client.get("/admin/usuarios?novo=1").text
    assert 'data-se-papel="client"' in html and "/clientes/opcoes?inativos=1" in html
    assert "Acme" in client.get("/clientes/opcoes?inativos=1&q=acm").text
    assert "Acme" not in client.get("/clientes/opcoes?q=acm").text
    r = client.post(
        "/admin/usuarios/novo",
        data={
            "csrf_token": client.cookies["tf_csrf"],
            "full_name": "Carla Cliente",
            "display_name": "Carla",
            "email": "carla@x.com",
            "username": "carla",
            "password": "Provisoria#2026",
            "role": "client",
            "client_id": acme,
            "cliente_nome": "Acme",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    carla = db.scalar(select(User).where(User.email == "carla@x.com"))
    assert carla is not None and carla.client is not None and carla.client.name == "Acme"
    html = client.get(f"/admin/usuarios?editar={carla.public_id}").text
    assert 'name="cliente_nome" value="Acme"' in html
