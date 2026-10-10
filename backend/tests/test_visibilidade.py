"""Quem vê cada chamado (docs/08 §8.4), tabelado: F1-S3-10."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from chamados.core.permissions import Actor
from chamados.modules.audit.models import AuditLog
from chamados.modules.catalog.models import TicketStatus
from chamados.modules.identity.models import User
from chamados.modules.tickets.models import Ticket, TicketTeam, TicketWatcher
from chamados.modules.tickets.visibility import ticket_visibility_filter
from tests.conftest import criar_categoria, criar_usuario, entrar, grupo

# Chamados do cenário (pelo título) e quem os vê
CHAMADOS = {
    "do TI": "regra 1: só o TI",
    "transferido do TI": "regra 2: o TI atuou antes, agora está na Infra",
    "confidencial transferido do TI": "regra 2 não vale para confidencial",
    "atribuído à Ana na Infra": "regra 3: responsável, mesmo fora do grupo",
    "confidencial observado pela Bia": "regra 4: observador",
}
TODOS = set(CHAMADOS)
ESPERADO = {
    "ana": {"do TI", "transferido do TI", "atribuído à Ana na Infra"},
    "bia": {"transferido do TI", "atribuído à Ana na Infra", "confidencial observado pela Bia"},
    "caio": {"confidencial transferido do TI", "confidencial observado pela Bia"},
    "admin": TODOS,
    "auditor": TODOS,
    "sem grupo": set(),
}


def _cenario(db: Session) -> dict[str, User]:
    users = {
        "ana": criar_usuario(db, "ana@x.com", grupos={"TI": "member"}),
        "bia": criar_usuario(db, "bia@x.com", grupos={"Infra": "supervisor"}),
        "caio": criar_usuario(db, "caio@x.com", grupos={"RH": "member"}),
        "admin": criar_usuario(db, "admin@x.com", "admin"),
        "auditor": criar_usuario(db, "auditor@x.com", "auditor"),
        "sem grupo": criar_usuario(db, "dino@x.com"),
    }
    normal = criar_categoria(db, "Impressão")
    folha = criar_categoria(db, "Folha", confidencial=True)
    pendente = db.scalar(select(TicketStatus).where(TicketStatus.kind == "open"))
    assert pendente
    ti, infra, rh = grupo(db, "TI"), grupo(db, "Infra"), grupo(db, "RH")

    def chamado(
        titulo: str, team_atual: int, antes: list[int], categoria: int, **extra: int
    ) -> Ticket:
        t = Ticket(
            title=titulo,
            type="incident",
            created_by_id=users["admin"].id,
            team_id=team_atual,
            category_id=categoria,
            status_id=pendente.id,
            impact=1,
            urgency=1,
            priority=1,
            **extra,
        )
        db.add(t)
        db.flush()
        for team_id in {team_atual, *antes}:
            db.add(TicketTeam(ticket_id=t.id, team_id=team_id))
        return t

    chamado("do TI", ti.id, [], normal.id)
    chamado("transferido do TI", infra.id, [ti.id], normal.id)
    chamado("confidencial transferido do TI", rh.id, [ti.id], folha.id)
    chamado("atribuído à Ana na Infra", infra.id, [], normal.id, assignee_id=users["ana"].id)
    observado = chamado("confidencial observado pela Bia", rh.id, [], folha.id)
    db.add(TicketWatcher(ticket_id=observado.id, user_id=users["bia"].id, kind="mentioned"))
    db.commit()
    return users


def _ator(db: Session, user: User) -> Actor:
    db.refresh(user)
    return Actor(
        user_id=user.id,
        role=user.role.code,
        teams=frozenset(m.team_id for m in user.memberships),
        supervises=frozenset(m.team_id for m in user.memberships if m.role == "supervisor"),
    )


def _numeros(db: Session) -> dict[str, int]:
    return {
        titulo: numero for titulo, numero in db.execute(text("SELECT title, number FROM tickets"))
    }


@pytest.mark.parametrize("quem", list(ESPERADO))
def test_filtro_de_visibilidade(db: Session, quem: str) -> None:
    users = _cenario(db)
    vistos = db.scalars(
        select(Ticket.title).where(ticket_visibility_filter(_ator(db, users[quem])))
    ).all()
    assert set(vistos) == ESPERADO[quem]


def test_lista_e_detalhe_usam_o_filtro(client: TestClient, db: Session) -> None:
    _cenario(db)
    entrar(client, "ana@x.com")
    titulos = {t["title"] for t in client.get("/api/v1/tickets").json()["items"]}
    assert titulos == ESPERADO["ana"]

    numeros = _numeros(db)
    r = client.get(f"/api/v1/tickets/{numeros['confidencial transferido do TI']}")
    assert r.status_code == 403
    assert r.json()["detail"] == "Você não tem acesso a este chamado."
    url = f"/api/v1/tickets/{numeros['confidencial transferido do TI']}"
    for sub in ("/comments", "/events"):
        assert client.get(url + sub).status_code == 403
    assert client.get("/api/v1/tickets/999999").status_code == 404
    assert client.get("/api/v1/tickets/nao-existe").status_code == 404


def test_confidencial_lido_pelo_auditor_vai_para_a_auditoria(
    client: TestClient, db: Session
) -> None:
    _cenario(db)
    entrar(client, "auditor@x.com")
    numeros = _numeros(db)
    r = client.get(f"/api/v1/tickets/{numeros['confidencial observado pela Bia']}")
    assert r.status_code == 200
    assert r.json()["allowed_actions"] == []
    assert client.get(f"/api/v1/tickets/{numeros['do TI']}").status_code == 200

    acessos = db.scalars(
        select(AuditLog).where(AuditLog.action == "ticket.confidential_viewed")
    ).all()
    assert [a.target_id for a in acessos] == [r.json()["id"]]
