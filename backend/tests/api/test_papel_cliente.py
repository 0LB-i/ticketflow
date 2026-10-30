"""Papel Cliente (docs/08): a empresa no cadastro do usuário, sem grupos, sem a API e sem tokens;
vê os chamados da empresa dele, todos, e nenhum outro."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from chamados.modules.clients.models import Client
from chamados.modules.identity.deps import actor_of
from chamados.modules.identity.models import User
from chamados.modules.organization.models import Role
from chamados.modules.tickets.models import Ticket
from chamados.modules.tickets.visibility import ticket_visibility_filter
from tests.apoio import NOVO_USUARIO, com_token, criar_token, registrar
from tests.conftest import criar_categoria, criar_cliente, criar_usuario, entrar, grupo

CLIENTE = {**NOVO_USUARIO, "role": "client"}


def usuario_cliente(db: Session, cliente: str, email: str = "cli@x.com") -> User:
    """Um usuário com o papel Cliente, da empresa `cliente` (id público)."""
    user = criar_usuario(db, email, "client", nome="Cliente")
    user.client_id = db.scalar(select(Client.id).where(Client.public_id == uuid.UUID(cliente)))
    db.commit()
    return user


def _admin(client: TestClient, db: Session) -> None:
    criar_usuario(db, "admin@exemplo.com", "admin", nome="Admin")
    entrar(client, "admin@exemplo.com")


def test_criar_usuario_cliente_pede_a_empresa(client: TestClient, db: Session) -> None:
    _admin(client, db)
    r = client.post("/api/v1/users", json=CLIENTE)
    assert r.status_code == 422
    assert r.json()["detail"] == "Escolha a empresa do usuário com o papel Cliente."
    # Qualquer cadastro, inclusive um inativo.
    inativo = criar_cliente(db, "Acme", "33445566000186", ativo=False)
    r = client.post("/api/v1/users", json={**CLIENTE, "client_id": inativo})
    assert r.status_code == 201, r.text
    assert r.json()["client"] == {"id": inativo, "name": "Acme"}


def test_empresa_so_no_papel_cliente(client: TestClient, db: Session) -> None:
    _admin(client, db)
    acme = criar_cliente(db, "Acme", "33445566000186")
    r = client.post("/api/v1/users", json={**NOVO_USUARIO, "client_id": acme})
    assert r.status_code == 201
    assert r.json()["client"] is None
    bruno = r.json()["id"]
    r = client.patch(f"/api/v1/users/{bruno}", json={"role": "client"})
    assert r.status_code == 422  # sem a empresa
    r = client.patch(f"/api/v1/users/{bruno}", json={"role": "client", "client_id": acme})
    assert r.json()["client"]["name"] == "Acme"
    # Mudar o nome não tira a empresa; sair do papel, sim.
    assert client.patch(f"/api/v1/users/{bruno}", json={"full_name": "Bruno L."}).json()["client"]
    assert client.patch(f"/api/v1/users/{bruno}", json={"role": "agent"}).json()["client"] is None


def test_papel_cliente_nao_entra_em_grupos(client: TestClient, db: Session) -> None:
    _admin(client, db)
    acme = criar_cliente(db, "Acme", "33445566000186")
    ti = str(grupo(db, "TI").public_id)
    r = client.post("/api/v1/users", json={**CLIENTE, "client_id": acme, "team_ids": [ti]})
    assert r.status_code == 422
    cli = usuario_cliente(db, acme)
    r = client.put(f"/api/v1/teams/{ti}/members/{cli.public_id}", json={"role": "member"})
    assert r.status_code == 422
    assert r.json()["detail"] == "Quem tem o papel Cliente não entra em grupos."
    # Quem está num grupo sai dele antes de virar Cliente.
    ana = criar_usuario(db, "ana@x.com", grupos={"TI": "member"})
    r = client.patch(f"/api/v1/users/{ana.public_id}", json={"role": "client", "client_id": acme})
    assert r.status_code == 409


def test_papel_cliente_nao_usa_a_api(client: TestClient, db: Session) -> None:
    usuario_cliente(db, criar_cliente(db, "Acme", "33445566000186"))
    entrar(client, "cli@x.com")
    assert client.get("/api/v1/me").status_code == 200
    assert client.get("/api/v1/tickets").status_code == 403
    assert client.get("/api/v1/clients/options").status_code == 403


def test_token_de_quem_virou_cliente_nao_vale(client: TestClient, db: Session) -> None:
    ana = criar_usuario(db, "ana@x.com")
    api = com_token(client, criar_token(db, "ana@x.com"))
    assert api.get("/api/v1/me").status_code == 200
    ana.role_id = db.scalars(select(Role.id).where(Role.code == "client")).one()
    db.commit()
    assert api.get("/api/v1/me").status_code == 401


def test_cliente_ve_todos_os_chamados_da_empresa_e_so_eles(
    client: TestClient, db: Session, cenario: dict[str, str]
) -> None:
    acme = cenario["cliente"]
    outra = criar_cliente(db, "Outra", "11222333000181")
    confidencial = str(criar_categoria(db, "RH", grupo_padrao="TI", confidencial=True).public_id)
    registrar(client, cenario, title="Da empresa")
    registrar(client, cenario, title="Confidencial", category_id=confidencial)
    registrar(client, cenario, title="De outra", client_id=outra)
    cli = usuario_cliente(db, acme)
    vistos = db.scalars(select(Ticket.title).where(ticket_visibility_filter(actor_of(cli))))
    assert sorted(vistos) == ["Confidencial", "Da empresa"]
