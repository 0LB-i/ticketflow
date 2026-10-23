"""Idempotency-Key nos POST com token de API (identity/idempotency.py, docs/05)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from chamados.config import Settings
from chamados.modules.identity.idempotency import digest
from chamados.modules.identity.models import IdempotencyKey
from chamados.modules.jobs.service import cleanup
from chamados.modules.tickets.models import Ticket
from tests.conftest import criar_usuario
from tests.test_chamados import API, base, cenario  # noqa: F401
from tests.test_fila import rodar
from tests.test_tokens_api import com_token, criar_token


def _novo(c: dict[str, Any], titulo: str = "Pelo agente") -> dict[str, Any]:
    return {**base(c), "title": titulo, "category_id": c["impressao"]}


def _chamados(db: Session) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(Ticket)) or 0


def test_repetir_devolve_a_mesma_resposta_sem_registrar_de_novo(
    client: TestClient,
    cenario: dict[str, Any],  # noqa: F811
    db: Session,
) -> None:
    com_token(client, criar_token(db, "ana@x.com"))
    chave = {"Idempotency-Key": "pedido-1"}
    primeira = client.post(API, json=_novo(cenario), headers=chave)
    assert primeira.status_code == 201, primeira.text
    segunda = client.post(API, json=_novo(cenario), headers=chave)
    assert segunda.status_code == 201
    assert segunda.json() == primeira.json()
    assert segunda.headers["location"] == primeira.headers["location"]
    assert segunda.headers["idempotent-replayed"] == "true"
    assert "idempotent-replayed" not in primeira.headers
    assert _chamados(db) == 1

    # Outra chave, ou sem chave: outro chamado
    assert (
        client.post(API, json=_novo(cenario), headers={"Idempotency-Key": "2"}).status_code == 201
    )
    assert client.post(API, json=_novo(cenario)).status_code == 201
    assert _chamados(db) == 3


def test_a_chave_vale_por_token(
    client: TestClient,
    cenario: dict[str, Any],  # noqa: F811
    db: Session,
) -> None:
    chave = {"Idempotency-Key": "pedido-1"}
    com_token(client, criar_token(db, "ana@x.com"))
    assert client.post(API, json=_novo(cenario), headers=chave).status_code == 201
    com_token(client, criar_token(db, "ana@x.com"))
    assert client.post(API, json=_novo(cenario), headers=chave).status_code == 201
    assert _chamados(db) == 2


def test_sessao_da_interface_ignora_a_chave(
    client: TestClient,
    cenario: dict[str, Any],  # noqa: F811
    db: Session,
) -> None:
    chave = {"Idempotency-Key": "pedido-1"}
    assert client.post(API, json=_novo(cenario), headers=chave).status_code == 201
    assert client.post(API, json=_novo(cenario), headers=chave).status_code == 201
    assert _chamados(db) == 2


def test_mesma_chave_com_outra_requisicao(
    client: TestClient,
    cenario: dict[str, Any],  # noqa: F811
    db: Session,
) -> None:
    com_token(client, criar_token(db, "ana@x.com"))
    chave = {"Idempotency-Key": "pedido-1"}
    assert client.post(API, json=_novo(cenario), headers=chave).status_code == 201
    r = client.post(API, json=_novo(cenario, "Outro título"), headers=chave)
    assert r.status_code == 422
    assert r.json()["detail"] == "Esta Idempotency-Key já foi usada com outra requisição."
    assert _chamados(db) == 1


def test_erro_nao_fica_guardado(
    client: TestClient,
    cenario: dict[str, Any],  # noqa: F811
    db: Session,
) -> None:
    com_token(client, criar_token(db, "ana@x.com"))
    chave = {"Idempotency-Key": "pedido-1"}
    assert client.post(API, json={**_novo(cenario), "title": ""}, headers=chave).status_code == 422
    assert db.scalar(select(func.count()).select_from(IdempotencyKey)) == 0
    # A mesma chave, com o pedido corrigido, passa
    assert client.post(API, json=_novo(cenario), headers=chave).status_code == 201


def test_em_andamento_e_abandonada(
    client: TestClient,
    cenario: dict[str, Any],  # noqa: F811
    db: Session,
) -> None:
    raw = criar_token(db, "ana@x.com")
    com_token(client, raw)
    corpo = _novo(cenario)
    pedido = client.build_request("POST", API, json=corpo)
    em_andamento = IdempotencyKey(
        owner_hash=digest(f"Bearer {raw}".encode()),
        key="pedido-1",
        fingerprint=digest(b"POST", API.encode(), b"", pedido.content),
    )
    db.add(em_andamento)
    db.commit()
    chave = {"Idempotency-Key": "pedido-1"}
    r = client.post(API, json=corpo, headers=chave)
    assert r.status_code == 409
    assert _chamados(db) == 0

    # Parada há mais de 5 minutos (o processo caiu): a nova assume a chave
    em_andamento.created_at = datetime.now(UTC) - timedelta(minutes=6)
    db.commit()
    assert client.post(API, json=corpo, headers=chave).status_code == 201
    assert _chamados(db) == 1


def test_chave_grande_demais(client: TestClient, db: Session) -> None:
    criar_usuario(db, "ana@x.com")
    com_token(client, criar_token(db, "ana@x.com"))
    r = client.post(API, json={}, headers={"Idempotency-Key": "x" * 256})
    assert r.status_code == 422
    assert r.json()["detail"] == "Idempotency-Key: de 1 a 255 caracteres."


def test_limpeza_diaria(db: Session, settings: Settings) -> None:
    db.add_all(
        [
            IdempotencyKey(owner_hash="a", key="nova", fingerprint="f"),
            IdempotencyKey(
                owner_hash="a",
                key="velha",
                fingerprint="f",
                created_at=datetime.now(UTC) - timedelta(hours=25),
            ),
        ]
    )
    db.commit()

    async def limpar(sm: async_sessionmaker[AsyncSession]) -> None:
        async with sm() as session:
            await cleanup(session, settings, {})

    rodar(settings, limpar)
    db.expire_all()
    assert list(db.scalars(select(IdempotencyKey.key))) == ["nova"]
