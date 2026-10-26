"""Notificações por e-mail dos chamados (F1-S4-04, docs/10 §10.10): do outbox ao e-mail."""

import re
from collections.abc import Callable
from email.message import EmailMessage
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from chamados.config import Settings
from chamados.modules.catalog.models import TicketStatus
from chamados.modules.jobs import service, worker
from chamados.modules.jobs.models import Job
from chamados.modules.notifications import messages, tasks
from tests.apoio import API, registrar, rodar, status_id
from tests.conftest import FakeMailer, criar_usuario, entrar

Enviados = Callable[[], dict[str, tuple[str, str]]]


@pytest.fixture
def enviados(settings: Settings, mailer: FakeMailer, monkeypatch: pytest.MonkeyPatch) -> Enviados:
    """Roda o worker até a fila esvaziar e devolve os e-mails novos: destinatário → (assunto,
    corpo). Um destinatário repetido faria o teste falhar (um e-mail por pessoa por ação)."""
    monkeypatch.setattr(tasks, "make_mailer", lambda _settings: mailer)

    def rodar_worker() -> dict[str, tuple[str, str]]:
        async def main(sm: async_sessionmaker[AsyncSession]) -> None:
            async with sm() as session:
                await service.relay(session, settings, worker.HANDLERS)
            while await service.run_next(sm, settings, worker.TASKS):
                pass

        rodar(settings, main)
        novos = {to: (assunto, corpo) for to, assunto, corpo in mailer.sent}
        assert len(novos) == len(mailer.sent), mailer.sent
        mailer.sent.clear()
        return novos

    return rodar_worker


def test_atribuido_a_alguem(
    client: TestClient,
    cenario: dict[str, Any],
    enviados: Enviados,
    settings: Settings,
) -> None:
    settings.app_base_url = "http://teste/"  # a "/" do fim não dobra no link
    numero = registrar(client, cenario, assignee=cenario["bia"])["number"]
    emails = enviados()
    assert list(emails) == ["bia@x.com"]  # a Ana registrou: quem causa não recebe
    assunto, corpo = emails["bia@x.com"]
    assert assunto == f"[#{numero}] Impressora não imprime: atribuído a você"
    assert "Olá, Bia." in corpo
    assert f"Ana atribuiu a você o chamado #{numero}" in corpo
    assert f"http://teste/chamados/{numero}" in corpo and "//chamados" not in corpo

    # Assumir (a própria Ana) não avisa ninguém; entrar como mais um responsável avisa.
    client.post(f"{API}/{numero}/assign", json={"assignee": "me"})
    assert enviados() == {}
    ids = [cenario["ana"], cenario["bia"]]
    assert client.put(f"{API}/{numero}/assignees", json={"assignee_ids": ids}).status_code == 200
    assert list(enviados()) == ["bia@x.com"]


def test_comentario_novo_e_mencao(
    client: TestClient,
    cenario: dict[str, Any],
    enviados: Enviados,
) -> None:
    numero = registrar(client, cenario, watcher_ids=[cenario["caio"]])["number"]
    assert enviados() == {}
    entrar(client, "bia@x.com")
    r = client.post(
        f"{API}/{numero}/comments",
        json={"body": "Troquei o toner, @Auditor confira.", "mention_ids": [cenario["auditor"]]},
    )
    assert r.status_code == 201, r.text
    emails = enviados()
    assert set(emails) == {"ana@x.com", "caio@x.com", "auditor@x.com"}  # a Bia comentou
    assunto, corpo = emails["ana@x.com"]
    assert assunto.endswith(": comentário novo")
    assert "Bia comentou o chamado" in corpo and "Troquei o toner, @Auditor confira." in corpo
    assert emails["auditor@x.com"][0].endswith(": você foi mencionado")

    # Mencionado e também responsável: um e-mail só, o da menção.
    client.post(f"{API}/{numero}/comments", json={"body": "@Ana", "mention_ids": [cenario["ana"]]})
    emails = enviados()
    assert emails["ana@x.com"][0].endswith(": você foi mencionado")
    assert set(emails) == {"ana@x.com", "caio@x.com", "auditor@x.com"}


def test_mencao_no_registro(
    client: TestClient,
    cenario: dict[str, Any],
    enviados: Enviados,
) -> None:
    registrar(client, cenario, mention_ids=[cenario["bia"]])
    emails = enviados()
    assert list(emails) == ["bia@x.com"]
    assert emails["bia@x.com"][0].endswith(": você foi mencionado")


def test_transferido(
    client: TestClient,
    cenario: dict[str, Any],
    db: Session,
    enviados: Enviados,
) -> None:
    criar_usuario(db, "dani@x.com", nome="Dani Lima", grupos={"Infra": "member"})
    criar_usuario(db, "edu@x.com", nome="Edu", grupos={"Infra": "member"}, ativo=False)
    numero = registrar(client, cenario)["number"]
    dados = {"team_id": cenario["infra"], "assignee_id": cenario["caio"], "reason": "É rede."}
    assert client.post(f"{API}/{numero}/transfer", json=dados).status_code == 200
    emails = enviados()
    assert set(emails) == {"caio@x.com", "dani@x.com"}  # o Edu está inativo
    assunto, corpo = emails["caio@x.com"]
    assert assunto.endswith(": atribuído a você")
    assert "É rede." in corpo  # o motivo vai junto
    assunto, corpo = emails["dani@x.com"]
    assert assunto.endswith(": transferido para o grupo Infra")
    assert "Olá, Dani." in corpo and "É rede." in corpo


def test_concluido_e_reaberto(
    client: TestClient,
    cenario: dict[str, Any],
    enviados: Enviados,
    db: Session,
) -> None:
    entrar(client, "bia@x.com")
    numero = registrar(client, cenario, assignee=cenario["ana"], watcher_ids=[cenario["caio"]])[
        "number"
    ]
    enviados()
    entrar(client, "ana@x.com")
    url = f"{API}/{numero}/transitions"
    concluir = {"action": "close", "comment": "Troquei o toner.", "resolution_code_id": 1}
    assert client.post(url, json=concluir).status_code == 200
    emails = enviados()
    assert set(emails) == {"bia@x.com", "caio@x.com"}  # quem registrou e o observador
    assunto, corpo = emails["bia@x.com"]
    assert assunto.endswith(": concluído")
    assert "Ana concluiu o chamado" in corpo and "Troquei o toner." in corpo

    entrar(client, "bia@x.com")
    assert client.post(url, json={"action": "reopen", "comment": "Voltou."}).status_code == 200
    emails = enviados()
    assert set(emails) == {"ana@x.com", "caio@x.com"}  # responsável e observador
    assert emails["ana@x.com"][0].endswith(": reaberto")

    # Aguardar não está na tabela do §10.10: o comentário dele não vira e-mail.
    entrar(client, "ana@x.com")
    assert client.post(url, json={"action": "wait", "comment": "Fornecedor."}).status_code == 200
    assert enviados() == {}

    # Mas quem foi mencionado no comentário da mudança é avisado (e passa a observar).
    retomar = {
        "action": "resume",
        "comment": "@Auditor confira",
        "mention_ids": [cenario["auditor"]],
    }
    assert client.post(url, json=retomar).status_code == 200
    emails = enviados()
    assert set(emails) == {"auditor@x.com"}
    assert emails["auditor@x.com"][0].endswith(": você foi mencionado")
    observadores = client.get(f"{API}/{numero}").json()["watchers"]
    assert {w["id"]: w["kind"] for w in observadores}[cenario["auditor"]] == "mentioned"

    # Na conclusão, o mencionado recebe o da menção, e os demais o de concluído.
    concluir["mention_ids"] = [cenario["auditor"], cenario["caio"]]
    assert client.post(url, json=concluir).status_code == 200
    emails = enviados()
    assert emails["auditor@x.com"][0].endswith(": você foi mencionado")
    assert emails["caio@x.com"][0].endswith(": você foi mencionado")
    assert emails["bia@x.com"][0].endswith(": concluído")

    # De um concluído para outro, ou para cancelado, não é conclusão nova nem reabertura.
    entrar(client, "bia@x.com")
    db.add(TicketStatus(name="Resolvido", kind="closed", sort_order=99))
    db.commit()
    for nome in ("Resolvido", "Cancelado"):
        mudar = {"status_id": int(status_id(client, nome))}
        assert client.patch(f"{API}/{numero}", json=mudar).status_code == 200
        assert enviados() == {}


def test_grupo_avisado_no_registro(
    client: TestClient,
    cenario: dict[str, Any],
    db: Session,
    enviados: Enviados,
) -> None:
    criar_usuario(db, "edu@x.com", nome="Edu", grupos={"TI": "member"})
    registrar(client, cenario)
    assert enviados() == {}  # padrão do grupo: só a fila

    db.execute(text("UPDATE teams SET notify_on_new = 'email_all_members' WHERE name = 'TI'"))
    db.commit()
    registrar(client, cenario, assignee=cenario["bia"])
    emails = enviados()
    assert set(emails) == {"bia@x.com", "edu@x.com"}
    assert emails["bia@x.com"][0].endswith(": atribuído a você")  # um e-mail só
    assert emails["edu@x.com"][0].endswith(": novo chamado no grupo TI")


def test_idioma_de_quem_recebe(
    client: TestClient,
    cenario: dict[str, Any],
    db: Session,
    enviados: Enviados,
) -> None:
    db.execute(text("UPDATE users SET locale = 'en' WHERE email = 'bia@x.com'"))
    db.commit()
    numero = registrar(client, cenario, assignee=cenario["bia"])["number"]
    assunto, corpo = enviados()["bia@x.com"]
    assert assunto == f"[#{numero}] Impressora não imprime: assigned to you"
    assert f"Ana assigned ticket #{numero} to you" in corpo


def test_smtp_fora_do_ar_volta_para_a_fila(
    client: TestClient,
    cenario: dict[str, Any],
    db: Session,
    mailer: FakeMailer,
    monkeypatch: pytest.MonkeyPatch,
    enviados: Enviados,
) -> None:
    def recusa(to: str, subject: str, body: str) -> None:
        raise ConnectionRefusedError

    monkeypatch.setattr(mailer, "deliver", recusa)
    registrar(client, cenario, assignee=cenario["bia"])
    assert enviados() == {}
    job = db.scalars(select(Job)).one()
    assert (job.task, job.status, job.attempts) == ("notifications.send_email", "queued", 1)
    assert job.args["to"] == "bia@x.com"


def test_textos_nos_dois_idiomas() -> None:
    pt, en = messages.TEXTS["pt-BR"], messages.TEXTS["en"]
    assert pt.keys() == en.keys()
    for chave in pt:
        for texto_pt, texto_en in zip(pt[chave], en[chave], strict=True):
            assert set(re.findall(r"{(\w+)}", texto_pt)) == set(re.findall(r"{(\w+)}", texto_en))


def test_assunto_sem_quebra_de_linha() -> None:
    """A API aceita quebra de linha no título; no assunto (um header), ela impediria o envio."""
    assunto, corpo = messages.render(
        "pt-BR",
        "transferred",
        nome="Bia",
        quem="Ana",
        numero=1000,
        titulo="Linha 1\nLinha 2",
        grupo="Suporte\r\nN2",
        url="http://teste/chamados/1000",
        comentario=None,
    )
    assert assunto == "[#1000] Linha 1 Linha 2: transferido para o grupo Suporte N2"
    EmailMessage()["Subject"] = assunto  # o que o SmtpMailer faz
    assert "Linha 1\nLinha 2" in corpo  # no corpo, o título fica como foi escrito


def test_rotina_de_envio_registrada() -> None:
    assert "notifications.send_email" in worker.TASKS
    # Os eventos que a tabela do §10.10 usa têm handler.
    assert set(worker.HANDLERS) >= {
        "ticket.created",
        "ticket.assigned",
        "ticket.assignees_changed",
        "ticket.transferred",
        "ticket.status_changed",
        "comment.created",
    }
