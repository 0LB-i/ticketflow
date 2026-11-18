"""O consumidor da ponte do WhatsApp (dentro do worker): grava os eventos e só então confirma."""

import asyncio
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from chamados.config import Settings
from chamados.modules.whatsapp import consumer, service
from chamados.modules.whatsapp.bridge import Bridge
from chamados.modules.whatsapp.models import WhatsAppChannel, WhatsAppMessage
from tests.apoio import rodar
from tests.conftest import grupo


class PonteComEventos(Bridge):
    def __init__(self, eventos: list[dict[str, Any]]) -> None:
        super().__init__(socket=None)  # type: ignore[arg-type]
        self.eventos = eventos
        self.confirmados: list[int] = []

    async def events(self, wait: int) -> list[dict[str, Any]]:
        return self.eventos

    async def ack(self, upto: int) -> None:
        self.confirmados.append(upto)


def _canal(db: Session) -> WhatsAppChannel:
    canal = WhatsAppChannel(name="Suporte", team_id=grupo(db, "Suporte").id)
    db.add(canal)
    db.commit()
    return canal


def _evento(canal: WhatsAppChannel, seq: int, wa_id: str) -> dict[str, Any]:
    return {
        "seq": seq,
        "type": "message",
        "channel": str(canal.public_id),
        "id": wa_id,
        "jid": "5511999990000@s.whatsapp.net",
        "from_me": False,
        "ts": 1763470000,
        "kind": "text",
        "text": "Oi",
    }


def test_grava_e_confirma_ate_o_ultimo(db: Session, settings: Settings) -> None:
    canal = _canal(db)
    ponte = PonteComEventos([_evento(canal, 7, "A"), _evento(canal, 9, "B")])

    async def lote(sm: async_sessionmaker[AsyncSession]) -> int:
        return await consumer.drain(sm, ponte, 0)

    assert rodar(settings, lote) == 2
    assert ponte.confirmados == [9]
    assert sorted(db.scalars(select(WhatsAppMessage.wa_id))) == ["A", "B"]


def test_sem_gravar_nao_confirma(
    db: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Se a gravação falha, a ponte guarda os eventos e entrega de novo."""
    canal = _canal(db)
    ponte = PonteComEventos([_evento(canal, 1, "A")])

    async def falha(_db: AsyncSession, _events: Any) -> None:
        raise RuntimeError("banco fora do ar")

    monkeypatch.setattr(service, "ingest", falha)

    async def lote(sm: async_sessionmaker[AsyncSession]) -> int:
        return await consumer.drain(sm, ponte, 0)

    with pytest.raises(RuntimeError):
        rodar(settings, lote)
    assert ponte.confirmados == []


def test_sem_a_ponte_espera_e_para_com_o_worker(settings: Settings) -> None:
    """Sem a ponte instalada, o consumidor espera e sai no pedido de parada."""

    async def roda(sm: async_sessionmaker[AsyncSession]) -> None:
        stop = asyncio.Event()
        tarefa = asyncio.create_task(consumer.run(sm, settings, stop))
        await asyncio.sleep(0.2)
        stop.set()
        await asyncio.wait_for(tarefa, 2)

    rodar(settings, roda)
