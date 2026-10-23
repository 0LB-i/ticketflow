"""Anexos (docs/11): envio em duas etapas, tipos, limites, vínculo, download e limpeza.

Cenário (a fixture `cenario`): Ana e Bia (supervisora) no TI, Caio na Infra.
"""

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from chamados.config import Settings
from chamados.db.engine import create_engine
from chamados.db.session import make_sessionmaker
from chamados.modules.attachments import router as attachments_router
from chamados.modules.attachments import service as attachments_service
from chamados.modules.attachments.files import clean_filename
from tests.apoio import API, PNG, anexo, enviar, registrar
from tests.conftest import entrar

PDF = b"%PDF-1.7\n" + b"x" * 32


def test_envio_e_download_antes_do_vinculo(
    client: TestClient,
    cenario: dict[str, Any],
    settings: Settings,
) -> None:
    r = enviar(client, "Tela do erro.png", PNG)
    assert r.status_code == 201
    enviado = r.json()
    assert enviado["filename"] == "Tela do erro.png"
    assert enviado["content_type"] == "image/png"  # pelo conteúdo, não pelo navegador
    assert enviado["size_bytes"] == len(PNG) and enviado["comment_id"] is None
    assert len(list((settings.files_dir / "attachments").rglob("*"))) == 3  # AAAA/MM/arquivo

    baixado = client.get(f"/api/v1/attachments/{enviado['id']}")
    assert baixado.status_code == 200 and baixado.content == PNG
    assert baixado.headers["content-disposition"].startswith("inline")
    assert baixado.headers["x-content-type-options"] == "nosniff"
    assert baixado.headers["content-security-policy"] == "sandbox"

    # Ainda não vinculado: só quem enviou baixa
    entrar(client, "bia@x.com")
    assert client.get(f"/api/v1/attachments/{enviado['id']}").status_code == 404


@pytest.mark.parametrize(
    ("nome", "conteudo", "status", "mensagem"),
    [
        ("programa.exe", b"MZ\x90\x00", 422, "Tipo de arquivo não permitido."),
        ("desenho.svg", b"<svg onload=alert(1)>", 422, "Tipo de arquivo não permitido."),
        ("pagina.html", b"<script>", 422, "Tipo de arquivo não permitido."),
        ("pacote.zip", b"PK\x03\x04", 422, "Tipo de arquivo não permitido."),
        ("sem-extensao", b"texto", 422, "Tipo de arquivo não permitido."),
        ("foto.png", b"<html>na verdade</html>", 422, "O conteúdo do arquivo não corresponde"),
        ("relatorio.pdf", PNG, 422, "O conteúdo do arquivo não corresponde"),
        ("log.txt", b"MZ\x00\x00binario", 422, "O conteúdo do arquivo não corresponde"),
        ("vazio.txt", b"", 422, "O arquivo está vazio."),
    ],
)
def test_tipos_recusados(
    client: TestClient,
    cenario: dict[str, Any],
    nome: str,
    conteudo: bytes,
    status: int,
    mensagem: str,
) -> None:
    r = enviar(client, nome, conteudo)
    assert r.status_code == status
    assert r.json()["detail"].startswith(mensagem)


def test_tipos_aceitos_e_limite_de_tamanho(
    client: TestClient,
    cenario: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for nome, conteudo in [
        ("contrato.PDF", PDF),
        ("planilha.xlsx", b"PK\x03\x04resto"),
        ("erro.log", "Falha na impressão às 10h".encode()),
        ("foto.jpeg", b"\xff\xd8\xff\xe0"),
    ]:
        assert enviar(client, nome, conteudo).status_code == 201, nome

    monkeypatch.setattr(attachments_router, "MAX_BYTES", 10)
    r = enviar(client, "grande.txt", b"x" * 11)
    assert r.status_code == 413 and r.json()["detail"] == "O arquivo passa do limite de 25 MB."

    entrar(client, "auditor@x.com")  # só lê: não envia
    assert enviar(client, "nota.txt", b"oi").status_code == 403


def test_nome_saneado() -> None:
    assert clean_filename("C:\\Users\\ana\\Desktop\\nota.txt") == "nota.txt"
    assert clean_filename("../../etc/pass\x00wd.txt") == "passwd.txt"
    # NFC: o "o" seguido do acento combinante vira "ó"
    assert clean_filename("  relat\u00f3rio\u0301 final.pdf ") == "relat\u00f3ri\u00f3 final.pdf"
    longo = clean_filename("a" * 300 + ".pdf")
    assert len(longo) == 255 and longo.endswith(".pdf")


def test_vinculo_no_registro_comentario_e_conclusao(
    client: TestClient,
    cenario: dict[str, Any],
) -> None:
    descricao = anexo(client, "antes.png")
    t = registrar(client, cenario, assignee="me", attachment_ids=[descricao])
    url = f"{API}/{t['number']}"
    assert [(a["id"], a["comment_id"]) for a in t["attachments"]] == [(descricao, None)]

    contrato = anexo(client, "contrato.pdf", PDF)
    r = client.post(f"{url}/comments", json={"body": "Segue", "attachment_ids": [contrato]})
    assert r.status_code == 201
    comentario = r.json()["id"]

    # Editar o comentário mandando de novo o que ele já tem não é "já usado"
    r = client.patch(
        f"{url}/comments/{comentario}",
        json={"body": "Segue o contrato", "attachment_ids": [contrato]},
    )
    assert r.status_code == 200

    solucao = anexo(client, "depois.png")
    r = client.post(
        f"{url}/transitions",
        json={
            "action": "close",
            "comment": "Resolvido",
            "resolution_code_id": 1,
            "attachment_ids": [solucao],
        },
    )
    assert r.status_code == 200
    anexos = r.json()["attachments"]
    assert [a["filename"] for a in anexos] == ["antes.png", "contrato.pdf", "depois.png"]
    assert anexos[1]["comment_id"] == comentario
    assert anexos[2]["comment_id"] is not None
    assert anexos[0]["uploaded_by"]["display_name"] == "Ana"

    # Uma vez só, e só por quem enviou
    r = client.post(f"{url}/comments", json={"body": "De novo", "attachment_ids": [contrato]})
    assert r.status_code == 422 and r.json()["detail"] == "Anexo não encontrado ou já usado."
    da_ana = anexo(client)
    entrar(client, "bia@x.com")
    r = client.post(f"{url}/comments", json={"body": "Meu?", "attachment_ids": [da_ana]})
    assert r.status_code == 422


def test_download_segue_a_visibilidade(
    client: TestClient,
    cenario: dict[str, Any],
) -> None:
    contrato = anexo(client, "contrato.pdf", PDF)
    planilha = anexo(client, "custos.xlsx", b"PK\x03\x04")
    registrar(client, cenario, attachment_ids=[contrato, planilha])

    entrar(client, "bia@x.com")  # mesmo grupo
    r = client.get(f"/api/v1/attachments/{contrato}")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    r = client.get(f"/api/v1/attachments/{planilha}")
    assert r.headers["content-disposition"].startswith("attachment")
    assert "filename" in r.headers["content-disposition"]

    entrar(client, "caio@x.com")  # outro grupo
    assert client.get(f"/api/v1/attachments/{contrato}").status_code == 403
    entrar(client, "auditor@x.com")  # lê tudo
    assert client.get(f"/api/v1/attachments/{contrato}").status_code == 200


def test_limite_por_chamado(
    client: TestClient,
    cenario: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(attachments_service, "MAX_PER_TICKET", len(PNG) * 2)
    t = registrar(client, cenario, attachment_ids=[anexo(client), anexo(client)])
    r = client.post(
        f"{API}/{t['number']}/comments", json={"body": "Mais um", "attachment_ids": [anexo(client)]}
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "Os anexos deste chamado passariam do limite de 200 MB."


def test_limpeza_dos_envios_esquecidos(
    client: TestClient,
    cenario: dict[str, Any],
    settings: Settings,
    db: Session,
) -> None:
    esquecido = anexo(client, "esquecido.png")
    recente = anexo(client, "recente.png")
    usado = anexo(client, "usado.png")
    registrar(client, cenario, attachment_ids=[usado])
    db.execute(
        text(
            "UPDATE attachments SET created_at = now() - interval '25 hours' WHERE public_id <> :id"
        ),
        {"id": recente},
    )
    db.commit()

    async def limpar() -> int:
        engine = create_engine(settings.database_url)
        try:
            async with make_sessionmaker(engine)() as session:
                return await attachments_service.purge(session, settings.files_dir)
        finally:
            await engine.dispose()

    assert asyncio.run(limpar()) == 1
    assert client.get(f"/api/v1/attachments/{esquecido}").status_code == 404
    assert client.get(f"/api/v1/attachments/{recente}").status_code == 200
    assert client.get(f"/api/v1/attachments/{usado}").status_code == 200
    assert len([p for p in settings.files_dir.rglob("*") if p.is_file()]) == 2
