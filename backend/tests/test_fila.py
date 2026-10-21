"""Outbox, fila de tarefas e worker (F1-S4-03, docs/03 "Eventos de domínio")."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, time, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from chamados.config import Settings
from chamados.db.engine import create_engine
from chamados.db.session import make_sessionmaker
from chamados.modules.jobs import service, worker
from chamados.modules.jobs.models import Job, OutboxEvent
from chamados.modules.tickets.models import Ticket
from tests.test_chamados import API, cenario, registrar  # noqa: F401


def rodar[T](
    settings: Settings, fn: Callable[[async_sessionmaker[AsyncSession]], Awaitable[T]]
) -> T:
    """Roda `fn` com um sessionmaker assíncrono, como o worker faz."""

    async def main() -> T:
        engine = create_engine(settings.database_url)
        try:
            return await fn(make_sessionmaker(engine))
        finally:
            await engine.dispose()

    return asyncio.run(main())


def eventos_do_outbox(db: Session) -> list[OutboxEvent]:
    db.expire_all()
    return list(db.scalars(select(OutboxEvent).order_by(OutboxEvent.id)))


# --- outbox -----------------------------------------------------------------------------------


def test_eventos_do_chamado_vao_para_o_outbox(
    client: TestClient,
    cenario: dict[str, Any],  # noqa: F811
    db: Session,
) -> None:
    numero = registrar(client, cenario, mention_ids=[cenario["bia"]])["number"]
    ticket = db.scalars(select(Ticket).where(Ticket.number == numero)).one()
    r = client.post(
        f"{API}/{numero}/comments",
        json={"body": "Troquei o toner, @Bia.", "mention_ids": [cenario["bia"]]},
    )
    assert r.status_code == 201, r.text
    # O comentário de uma ação vai no evento dela (comment_id), sem um comment.created à parte.
    acao = {"action": "wait", "comment": "Aguardando o fornecedor"}
    assert client.post(f"{API}/{numero}/transitions", json=acao).status_code == 200

    criado, mencao, comentario, espera = eventos_do_outbox(db)
    assert criado.event_type == "ticket.created"
    assert criado.payload["ticket_id"] == ticket.id
    assert criado.payload["actor_user_id"] == ticket.created_by_id
    assert criado.payload["data"]["assignee"]["id"] == cenario["ana"]
    assert criado.payload["mention_ids"] == [cenario["bia"]]
    assert criado.processed_at is None
    assert (mencao.event_type, mencao.payload["data"]["kind"]) == ("watcher.added", "mentioned")
    # O comentário novo não vai para o histórico (ele é o próprio registro), mas vai para o
    # outbox: as notificações (docs/10 §10.10) precisam dele, com todos os mencionados (a Bia
    # já acompanhava o chamado, então não há outro watcher.added).
    assert comentario.event_type == "comment.created"
    assert comentario.payload["ticket_id"] == ticket.id
    assert comentario.payload["data"]["comment_id"] == r.json()["id"]
    assert comentario.payload["mention_ids"] == [cenario["bia"]]
    assert espera.event_type == "ticket.status_changed"
    assert "comment_id" in espera.payload["data"]


# --- fila -------------------------------------------------------------------------------------


def test_dois_workers_nao_pegam_a_mesma_tarefa(db: Session, settings: Settings) -> None:
    db.add_all(Job(task="teste.espera", args={"n": n}) for n in range(3))
    db.commit()
    rodando: list[int] = []

    async def tres_workers(sm: async_sessionmaker[AsyncSession]) -> list[bool]:
        # Cada tarefa só termina quando as três estão rodando ao mesmo tempo: sem o SKIP LOCKED,
        # um worker esperaria o lock do outro, a espera estouraria e a tarefa rodaria de novo.
        todas = asyncio.Event()

        async def espera(_db: AsyncSession, _s: Settings, args: dict[str, Any]) -> None:
            rodando.append(args["n"])
            if len(rodando) == 3:
                todas.set()
            await asyncio.wait_for(todas.wait(), 5)

        tasks = {"teste.espera": espera}
        result = await asyncio.gather(*(service.run_next(sm, settings, tasks) for _ in range(3)))
        return [*result, await service.run_next(sm, settings, tasks)]

    assert rodar(settings, tres_workers) == [True, True, True, False]
    assert sorted(rodando) == [0, 1, 2]
    db.expire_all()
    for job in db.scalars(select(Job)):
        assert (job.status, job.attempts, job.last_error) == ("done", 1, None)
        assert job.finished_at is not None


def test_tarefa_que_falha_volta_com_espera_e_tem_limite(db: Session, settings: Settings) -> None:
    db.add(Job(task="teste.falha", max_attempts=3))
    db.commit()

    async def falha(_db: AsyncSession, _s: Settings, _args: dict[str, Any]) -> None:
        raise RuntimeError("SMTP fora do ar")

    def tentar() -> bool:
        return rodar(settings, lambda sm: service.run_next(sm, settings, {"teste.falha": falha}))

    def estado() -> tuple[str, int, str | None, timedelta]:
        db.commit()  # transação nova: o now() é o de agora
        job = db.scalars(select(Job)).one()
        espera = db.scalar(select(Job.run_after - func.now()))
        assert espera is not None
        return job.status, job.attempts, job.last_error, espera

    def ja_pode() -> None:
        db.execute(text("UPDATE jobs SET run_after = now() - interval '1 second'"))
        db.commit()

    assert tentar()
    status, tentativas, erro, espera = estado()
    assert (status, tentativas) == ("queued", 1)
    assert erro is not None and "SMTP fora do ar" in erro
    assert timedelta(seconds=25) < espera <= timedelta(seconds=30)
    assert not tentar()  # ainda esperando

    ja_pode()
    assert tentar()
    status, tentativas, _, espera = estado()
    assert (status, tentativas) == ("queued", 2)
    assert timedelta(seconds=115) < espera <= timedelta(minutes=2)

    ja_pode()
    assert tentar()
    status, tentativas, erro, _ = estado()
    assert (status, tentativas) == ("failed", 3)
    assert db.scalars(select(Job.finished_at)).one() is not None
    ja_pode()
    assert not tentar()  # falhou de vez: não volta


# --- repasse do outbox ------------------------------------------------------------------------


async def avisar(db: AsyncSession, _settings: Settings, event: OutboxEvent) -> None:
    service.enqueue(db, "teste.avisar", ticket_id=event.payload["ticket_id"])


def repassar(settings: Settings, handlers: dict[str, service.Handler]) -> int:
    async def main(sm: async_sessionmaker[AsyncSession]) -> int:
        async with sm() as session:
            return await service.relay(session, settings, handlers)

    return rodar(settings, main)


def test_evento_de_transacao_desfeita_nao_vira_tarefa(
    client: TestClient,
    cenario: dict[str, Any],  # noqa: F811
    db: Session,
    settings: Settings,
) -> None:
    r = client.post(
        API,
        json={
            "client_id": cenario["cliente"],
            "assignee": "me",
            "title": "Impressora",
            "category_id": cenario["impressao"],
            "mention_ids": [str(uuid.uuid4())],
        },
    )
    assert r.status_code == 422, r.text
    assert repassar(settings, {"ticket.created": avisar}) == 0
    assert db.scalars(select(Job)).all() == []

    registrar(client, cenario)
    assert repassar(settings, {"ticket.created": avisar}) == 1
    db.expire_all()
    job = db.scalars(select(Job)).one()
    assert job.task == "teste.avisar"
    assert job.args == {"ticket_id": db.scalars(select(Ticket.id)).one()}
    assert all(e.processed_at is not None for e in eventos_do_outbox(db))
    assert repassar(settings, {"ticket.created": avisar}) == 0  # não repassa de novo


def test_handler_que_falha_nao_trava_os_outros(db: Session, settings: Settings) -> None:
    db.add_all(
        OutboxEvent(event_type=tipo, payload={"ticket_id": n})
        for n, tipo in enumerate(["teste.quebra", "ticket.created", "sem.handler"])
    )
    db.commit()

    async def quebra(session: AsyncSession, _settings: Settings, event: OutboxEvent) -> None:
        service.enqueue(session, "teste.avisar", ticket_id=-1)  # desfeito junto com a falha
        raise ValueError("payload inesperado")

    assert repassar(settings, {"teste.quebra": quebra, "ticket.created": avisar}) == 3
    quebrado, criado, sem_handler = eventos_do_outbox(db)
    assert quebrado.error == "ValueError: payload inesperado"
    assert criado.error is None and sem_handler.error is None
    assert all(e.processed_at is not None for e in (quebrado, criado, sem_handler))
    assert [j.args for j in db.scalars(select(Job))] == [{"ticket_id": 1}]


# --- rotinas ----------------------------------------------------------------------------------


def test_rotina_agendada_uma_vez_por_dia(db: Session, settings: Settings) -> None:
    rotinas = {"attachments.purge": time(3, 0)}

    def agendar(agora: datetime) -> None:
        async def main(sm: async_sessionmaker[AsyncSession]) -> None:
            async with sm() as session:
                await service.schedule(session, rotinas, agora)

        rodar(settings, main)

    # 21/10 às 23:30 em São Paulo ainda é dia 21, embora em UTC já seja 22.
    agendar(datetime(2026, 10, 22, 2, 30, tzinfo=UTC))
    agendar(datetime(2026, 10, 22, 2, 31, tzinfo=UTC))  # outro worker, ou a volta seguinte
    agendar(datetime(2026, 10, 22, 4, 0, tzinfo=UTC))  # dia 22 em São Paulo
    jobs = db.scalars(select(Job).order_by(Job.id)).all()
    assert [(j.task, j.dedup_key) for j in jobs] == [
        ("attachments.purge", "attachments.purge:2026-10-21"),
        ("attachments.purge", "attachments.purge:2026-10-22"),
    ]
    assert [j.run_after for j in jobs] == [
        datetime(2026, 10, 21, 6, 0, tzinfo=UTC),  # 03:00 em São Paulo
        datetime(2026, 10, 22, 6, 0, tzinfo=UTC),
    ]


def test_rotinas_do_worker_rodam(db: Session, settings: Settings) -> None:
    async def main(sm: async_sessionmaker[AsyncSession]) -> list[bool]:
        async with sm() as session:  # agendadas para ontem: já estão prontas
            await service.schedule(session, worker.ROUTINES, datetime.now(UTC) - timedelta(days=1))
        return [await service.run_next(sm, settings, worker.TASKS) for _ in worker.ROUTINES]

    assert rodar(settings, main) == [True] * len(worker.ROUTINES)
    assert {(j.task, j.status, j.last_error) for j in db.scalars(select(Job))} == {
        (task, "done", None) for task in worker.ROUTINES
    }


def test_limpeza_da_fila_e_do_outbox(db: Session, settings: Settings) -> None:
    def ha(dias: int) -> datetime:
        return datetime.now(UTC) - timedelta(days=dias)

    db.add_all(
        [
            Job(task="feita.antiga", status="done", finished_at=ha(8)),
            Job(task="feita.recente", status="done", finished_at=ha(6)),
            Job(task="falhou.recente", status="failed", finished_at=ha(8)),
            Job(task="falhou.antiga", status="failed", finished_at=ha(31)),
            Job(task="na.fila", created_at=ha(40)),
            OutboxEvent(event_type="processado.antigo", payload={}, processed_at=ha(8)),
            OutboxEvent(event_type="processado.recente", payload={}, processed_at=ha(6)),
            OutboxEvent(event_type="pendente", payload={}, created_at=ha(40)),
        ]
    )
    db.commit()

    async def limpar(sm: async_sessionmaker[AsyncSession]) -> None:
        async with sm() as session:
            await service.cleanup(session, settings, {})

    rodar(settings, limpar)
    db.expire_all()
    assert sorted(db.scalars(select(Job.task))) == ["falhou.recente", "feita.recente", "na.fila"]
    assert sorted(db.scalars(select(OutboxEvent.event_type))) == [
        "pendente",
        "processado.recente",
    ]


# --- worker -----------------------------------------------------------------------------------


def test_worker_termina_a_tarefa_em_curso_e_sai(
    db: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    db.add_all([Job(task="teste.para"), Job(task="teste.para")])
    db.commit()

    async def main() -> None:
        stop = asyncio.Event()

        async def para(_db: AsyncSession, _s: Settings, _args: dict[str, Any]) -> None:
            stop.set()  # o pedido de parada chega no meio da tarefa
            await asyncio.sleep(0.1)

        monkeypatch.setitem(worker.TASKS, "teste.para", para)
        monkeypatch.setattr(worker, "ROUTINES", {})
        await asyncio.wait_for(worker.run(settings, stop), 10)

    asyncio.run(main())
    assert [j.status for j in db.scalars(select(Job).order_by(Job.id))] == ["done", "queued"]
