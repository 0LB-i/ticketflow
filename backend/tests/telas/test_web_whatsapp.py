"""Chat do WhatsApp: os números na administração (/admin/whatsapp), as conversas (/whatsapp), o
envio com o nome de quem respondeu e o que chega da ponte. A ponte é falsa (PonteFalsa)."""

import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from chamados.config import Settings
from chamados.modules.audit.models import AuditLog
from chamados.modules.jobs.models import Job
from chamados.modules.whatsapp import service
from chamados.modules.whatsapp.bridge import DOWN, Bridge, BridgeError
from chamados.modules.whatsapp.models import (
    WhatsAppChannel,
    WhatsAppChannelManager,
    WhatsAppChat,
    WhatsAppMessage,
)
from chamados.web.whatsapp import bridge_dep
from tests.apoio import rodar
from tests.conftest import criar_usuario, entrar, grupo, token_csrf

CLIENTE = "5511999990000@s.whatsapp.net"
GRUPO_WA = "120363000000000000@g.us"


class PonteFalsa(Bridge):
    def __init__(self) -> None:
        super().__init__(socket=None)  # type: ignore[arg-type]
        self.fora = False
        self.estado: dict[uuid.UUID, dict[str, Any]] = {}
        self.enviadas: list[tuple[uuid.UUID, str, str, str]] = []
        self.midias: list[dict[str, Any]] = []
        self.iniciados: list[uuid.UUID] = []
        self.desconectados: list[uuid.UUID] = []

    def _confere(self) -> None:
        if self.fora:
            raise BridgeError(DOWN)

    async def channels(self) -> dict[uuid.UUID, dict[str, Any]]:
        self._confere()
        return self.estado

    async def start(self, channel: uuid.UUID) -> dict[str, Any]:
        self._confere()
        self.iniciados.append(channel)
        return {"state": "pairing"}

    async def logout(self, channel: uuid.UUID) -> None:
        self._confere()
        self.desconectados.append(channel)

    async def send_text(self, channel: uuid.UUID, jid: str, text: str, wa_id: str) -> None:
        self._confere()
        self.enviadas.append((channel, jid, text, wa_id))

    async def send_media(self, channel: uuid.UUID, jid: str, **dados: Any) -> None:
        self._confere()
        self.midias.append({"channel": channel, "jid": jid, **dados})


@pytest.fixture
def ponte(client: TestClient) -> Iterator[PonteFalsa]:
    falsa = PonteFalsa()
    client.app.dependency_overrides[bridge_dep] = lambda: falsa  # type: ignore[attr-defined]
    yield falsa
    client.app.dependency_overrides.pop(bridge_dep)  # type: ignore[attr-defined]


def _numero(db: Session, nome_grupo: str = "Suporte", **extra: Any) -> WhatsAppChannel:
    canal = WhatsAppChannel(name="Suporte", team_id=grupo(db, nome_grupo).id, **extra)
    db.add(canal)
    db.commit()
    return canal


def _chega(settings: Settings, *eventos: dict[str, Any]) -> None:
    async def gravar(sm: async_sessionmaker[AsyncSession]) -> None:
        async with sm() as s:
            await service.ingest(s, list(eventos))

    rodar(settings, gravar)


def _msg(canal: WhatsAppChannel, wa_id: str, texto: str | None, **extra: Any) -> dict[str, Any]:
    return {
        "type": "message",
        "channel": str(canal.public_id),
        "id": wa_id,
        "jid": CLIENTE,
        "from_me": False,
        "sender": CLIENTE,
        "push_name": "Maria Cliente",
        "ts": int(datetime(2026, 11, 18, 13, 0, tzinfo=UTC).timestamp()),
        "kind": "text",
        "text": texto,
        **extra,
    }


def _conversa(db: Session, jid: str = CLIENTE) -> WhatsAppChat:
    db.expire_all()
    chat = db.scalar(select(WhatsAppChat).where(WhatsAppChat.jid == jid))
    assert chat is not None
    return chat


# Administração ---------------------------------------------------------------------------------


def test_admin_cadastra_o_numero_escolhe_os_responsaveis_e_conecta(
    client: TestClient, db: Session, ponte: PonteFalsa
) -> None:
    criar_usuario(db, "adm@x.com", "admin", nome="Adm")
    ana = criar_usuario(db, "ana@x.com", nome="Ana", grupos={"Suporte": "member"})
    caio = criar_usuario(db, "caio@x.com", nome="Caio", grupos={"Infra": "member"})
    suporte = str(grupo(db, "Suporte").public_id)
    entrar(client, "adm@x.com")

    assert 'href="/admin/whatsapp"' in client.get("/chamados").text
    assert "Nenhum número cadastrado." in client.get("/admin/whatsapp").text

    r = client.post(
        "/admin/whatsapp",
        data={"csrf_token": token_csrf(client), "nome": "Suporte", "grupo": suporte},
    )
    assert r.status_code == 200, r.text  # o redirecionamento leva à tela do número
    canal = db.scalar(select(WhatsAppChannel))
    assert canal is not None and canal.state == "new"
    assert f"/admin/whatsapp/{canal.public_id}/conectar" in r.text

    url = f"/admin/whatsapp/{canal.public_id}"
    dados = {"csrf_token": token_csrf(client), "nome": "Suporte 2", "grupo": suporte}
    r = client.post(url, data={**dados, "responsaveis": [str(caio.public_id)]})
    assert r.status_code == 422
    assert "Os responsáveis precisam ser membros do grupo." in r.text

    r = client.post(url, data={**dados, "responsaveis": [str(ana.public_id)]})
    assert r.status_code == 200
    db.expire_all()
    assert canal.name == "Suporte 2" and canal.sign_messages is False  # sem o campo marcado
    assert [m.user_id for m in canal.managers] == [ana.id]
    # Salvar de novo com a mesma pessoa não troca nada (nem viola a chave).
    client.post(url, data={**dados, "responsaveis": [str(ana.public_id)], "assinar": "1"})
    db.expire_all()
    assert canal.sign_messages is True
    assert db.scalars(select(WhatsAppChannelManager)).all()[0].user_id == ana.id

    # Conectar: a ponte gera o QR code, que a tela mostra enquanto o pareamento não termina.
    client.post(url + "/conectar", data={"csrf_token": token_csrf(client)})
    assert ponte.iniciados == [canal.public_id]
    ponte.estado = {canal.public_id: {"state": "pairing", "qr_svg": "<svg id='qr'></svg>"}}
    html = client.get(url).text
    assert "<svg id='qr'></svg>" in html and 'hx-trigger="every 2s"' in html

    ponte.estado = {canal.public_id: {"state": "connected", "qr_svg": None}}
    html = client.get(url).text
    assert "Conectado" in html and "every 2s" not in html
    client.post(url + "/desconectar", data={"csrf_token": token_csrf(client)})
    assert ponte.desconectados == [canal.public_id]
    db.expire_all()
    assert canal.state == "logged_out"

    acoes = db.scalars(
        select(AuditLog.action)
        .where(AuditLog.target_type == "whatsapp_channel")
        .order_by(AuditLog.id)
    )
    assert list(acoes) == [
        "whatsapp_channel.created",
        "whatsapp_channel.updated",
        "whatsapp_channel.updated",
        "whatsapp_channel.disconnected",
    ]


def test_passkey_exigida_e_numero_parado_na_ponte(
    client: TestClient, db: Session, ponte: PonteFalsa
) -> None:
    criar_usuario(db, "adm@x.com", "admin", nome="Adm")
    canal = _numero(db, state="pairing")
    entrar(client, "adm@x.com")
    url = f"/admin/whatsapp/{canal.public_id}"
    # A ponte reiniciou e o pareamento ficou pela metade: a tela oferece o Conectar de novo.
    html = client.get(url).text
    assert "Não conectado" in html and "every 2s" not in html
    ponte.estado = {canal.public_id: {"state": "passkey_required", "qr_svg": None}}
    html = client.get(url).text
    assert "Exige passkey" in html and "Chaves de acesso" in html and "Tentar de novo" in html


def test_sem_a_ponte_a_tela_avisa(client: TestClient, db: Session, ponte: PonteFalsa) -> None:
    criar_usuario(db, "adm@x.com", "admin", nome="Adm")
    canal = _numero(db)
    entrar(client, "adm@x.com")
    ponte.fora = True
    aviso = "A ponte do WhatsApp não está rodando"
    assert aviso in client.get("/admin/whatsapp").text
    assert aviso in client.get(f"/admin/whatsapp/{canal.public_id}").text
    r = client.post(
        f"/admin/whatsapp/{canal.public_id}/conectar", data={"csrf_token": token_csrf(client)}
    )
    assert aviso in r.text


def test_agente_nao_administra_os_numeros(client: TestClient, db: Session) -> None:
    criar_usuario(db, "ana@x.com", nome="Ana", grupos={"Suporte": "member"})
    canal = _numero(db)
    entrar(client, "ana@x.com")
    assert 'href="/admin/whatsapp"' not in client.get("/chamados").text
    assert client.get("/admin/whatsapp").status_code == 403
    assert client.get(f"/admin/whatsapp/{canal.public_id}").status_code == 403


# Conversas -------------------------------------------------------------------------------------


def test_mensagens_que_chegam_aparecem_para_o_grupo_do_numero(
    client: TestClient, db: Session, settings: Settings
) -> None:
    criar_usuario(db, "ana@x.com", nome="Ana", grupos={"Suporte": "member"})
    criar_usuario(db, "caio@x.com", nome="Caio", grupos={"Infra": "member"})
    canal = _numero(db)
    _chega(
        settings,
        _msg(canal, "M1", "Bom dia, a impressora parou"),
        _msg(canal, "M1", "Bom dia, a impressora parou"),  # a ponte entregou de novo
        _msg(canal, "M2", "Alguém aí?"),
        _msg(canal, "H1", "Mensagem antiga", history=True, ts=1),
        {
            "type": "connection",
            "channel": str(canal.public_id),
            "state": "connected",
            "phone": "5511",
        },
        {"type": "message", "channel": str(uuid.uuid4()), "id": "X", "jid": CLIENTE},  # outro
    )
    chat = _conversa(db)
    assert chat.name == "Maria Cliente" and chat.unread == 2  # o histórico não conta
    assert db.scalar(select(WhatsAppChannel.state)) == "connected"
    assert len(db.scalars(select(WhatsAppMessage)).all()) == 3

    entrar(client, "ana@x.com")
    html = client.get("/whatsapp").text
    assert "Maria Cliente" in html and "Alguém aí?" in html
    assert "2 mensagens não lidas" in html

    html = client.get(f"/whatsapp/conversa/{chat.public_id}").text
    assert html.index("Mensagem antiga") < html.index("Bom dia, a impressora parou")
    assert _conversa(db).unread == 0  # abrir a conversa lê as mensagens

    # De outro grupo: não vê o número nem a conversa.
    caio = TestClient(client.app)
    caio.portal = client.portal
    entrar(caio, "caio@x.com")
    assert "Nenhum número do WhatsApp está ligado aos seus grupos." in caio.get("/whatsapp").text
    assert caio.get(f"/whatsapp/conversa/{chat.public_id}").status_code == 403


def _versao(html: str) -> str:
    # A do trecho que se atualiza (o menu do usuário repete o endereço pedido, com a antiga).
    achou = re.search(r'hx-get="/whatsapp/conversa/[^"?]+\?versao=([0-9-]+)&amp;', html)
    assert achou is not None
    return achou.group(1)


def test_a_conversa_aberta_so_atualiza_quando_algo_muda(
    client: TestClient, db: Session, settings: Settings
) -> None:
    """Mensagem nova, tick novo ou arquivo baixado: a tela troca; sem mudança, 204."""
    criar_usuario(db, "ana@x.com", nome="Ana", grupos={"Suporte": "member"})
    canal = _numero(db)
    _chega(
        settings,
        _msg(canal, "M1", "Primeira"),
        _msg(canal, "N1", "Nossa", from_me=True, sender=None),
        _msg(canal, "F1", None, kind="image", mime="image/jpeg"),
    )
    chat = _conversa(db)
    entrar(client, "ana@x.com")
    url = f"/whatsapp/conversa/{chat.public_id}"
    versao = _versao(client.get(url).text)
    assert client.get(url, params={"versao": versao}).status_code == 204

    _chega(settings, _msg(canal, "M2", "Segunda"))
    r = client.get(url, params={"versao": versao})
    assert r.status_code == 200 and "Segunda" in r.text
    versao = _versao(r.text)

    # O aviso vem pelo LID do contato, e a conversa está guardada pelo número: acha pelo id.
    status = {"type": "status", "channel": str(canal.public_id), "jid": "123@lid", "id": "N1"}
    _chega(settings, {**status, "status": "read"})
    r = client.get(url, params={"versao": versao})
    assert r.status_code == 200 and "Lida" in r.text
    versao = _versao(r.text)
    # O "entregue" atrasado não volta o tick.
    _chega(settings, {**status, "status": "delivered"})
    assert client.get(url, params={"versao": versao}).status_code == 204
    # A confirmação de uma mensagem do contato não vira tick.
    _chega(settings, {**status, "id": "M1", "status": "read"})
    assert (
        db.scalar(select(WhatsAppMessage.status).where(WhatsAppMessage.wa_id == "M1")) == "received"
    )

    media = settings.whatsapp_dir / "media"
    (media / "in" / "c").mkdir(parents=True)
    (media / "in" / "c" / "F1").write_bytes(b"\xff\xd8foto")
    _chega(
        settings,
        {
            "type": "media",
            "channel": str(canal.public_id),
            "jid": CLIENTE,
            "id": "F1",
            "path": "in/c/F1",
            "mime": "image/jpeg",
            "size": 6,
        },
    )
    r = client.get(url, params={"versao": versao})
    assert r.status_code == 200
    foto = db.scalar(select(WhatsAppMessage).where(WhatsAppMessage.wa_id == "F1"))
    assert foto is not None and f'<img src="{url}/arquivo/{foto.id}"' in r.text
    arquivo = client.get(f"{url}/arquivo/{foto.id}")
    assert arquivo.status_code == 200 and arquivo.content == b"\xff\xd8foto"
    assert arquivo.headers["content-type"] == "image/jpeg"
    assert arquivo.headers["content-disposition"].startswith("inline")


def test_abas_todas_nao_lidas_e_lidas(client: TestClient, db: Session, settings: Settings) -> None:
    criar_usuario(db, "ana@x.com", nome="Ana", grupos={"Suporte": "member"})
    canal = _numero(db)
    outro = "5511888880000@s.whatsapp.net"
    _chega(
        settings,
        _msg(canal, "M1", "Mensagem da Maria"),
        _msg(canal, "M2", "Mensagem do João", jid=outro, sender=outro, push_name="João"),
    )
    joao = _conversa(db, outro)
    joao.unread = 0
    db.commit()
    entrar(client, "ana@x.com")
    html = client.get("/whatsapp").text
    assert "+55" not in html.split('id="lista-conversas"')[0]  # o número saiu do topo
    assert "Maria Cliente" in html and "João" in html
    nao_lidas = client.get("/whatsapp", params={"filtro": "nao_lidas"}).text
    assert "Maria Cliente" in nao_lidas and "João" not in nao_lidas
    lidas = client.get("/whatsapp", params={"filtro": "lidas"}).text
    assert "João" in lidas and "Maria Cliente" not in lidas
    # Aberta, a conversa fica lida e sai da aba Não lidas na hora.
    maria = _conversa(db)
    html = client.get(f"/whatsapp/conversa/{maria.public_id}", params={"filtro": "nao_lidas"}).text
    assert "Nenhuma conversa aqui." in html


def test_no_grupo_do_whatsapp_aparece_quem_mandou(
    client: TestClient, db: Session, settings: Settings
) -> None:
    criar_usuario(db, "ana@x.com", nome="Ana", grupos={"Suporte": "member"})
    canal = _numero(db)
    _chega(
        settings,
        _msg(
            canal,
            "G1",
            "Bom dia, grupo",
            jid=GRUPO_WA,
            chat_name="Clientes ACME",
            sender="5511888880000@s.whatsapp.net",
            push_name="João ACME",
        ),
        _msg(
            canal,
            "G2",
            "Sem nome",
            jid=GRUPO_WA,
            sender="5511777770000@s.whatsapp.net",
            push_name=None,
        ),
    )
    chat = _conversa(db, GRUPO_WA)
    assert chat.is_group and chat.name == "Clientes ACME"
    entrar(client, "ana@x.com")
    html = client.get(f"/whatsapp/conversa/{chat.public_id}").text
    assert "João ACME" in html and "+5511777770000" in html


def test_envio_vai_com_o_nome_em_negrito_e_aparece_em_cima_da_mensagem(
    client: TestClient, db: Session, settings: Settings, ponte: PonteFalsa
) -> None:
    criar_usuario(db, "ana@x.com", nome="Ana Souza", grupos={"Suporte": "member"})
    canal = _numero(db)
    _chega(settings, _msg(canal, "M1", "Oi"))
    chat = _conversa(db)
    entrar(client, "ana@x.com")
    url = f"/whatsapp/conversa/{chat.public_id}/enviar"

    r = client.post(url, data={"csrf_token": token_csrf(client), "texto": "  Já vou ver  "})
    assert r.status_code == 200
    [(canal_id, jid, texto, wa_id)] = ponte.enviadas
    assert (canal_id, jid, texto) == (canal.public_id, CLIENTE, "*Ana Souza:*\nJá vou ver")
    enviada = db.scalar(select(WhatsAppMessage).where(WhatsAppMessage.wa_id == wa_id))
    assert enviada is not None and enviada.body == "Já vou ver" and enviada.status == "sent"
    assert "Ana Souza" in r.text and "Já vou ver" in r.text

    # A cópia que o WhatsApp devolve (mesmo id) não entra de novo; a mandada pelo celular entra.
    _chega(
        settings,
        _msg(canal, wa_id, "*Ana Souza:*\nJá vou ver", from_me=True, sender=None),
        _msg(canal, "CEL1", "Mandei pelo celular", from_me=True, sender=None),
    )
    assert len(db.scalars(select(WhatsAppMessage)).all()) == 3
    html = client.get(f"/whatsapp/conversa/{chat.public_id}").text
    assert "Pelo celular" in html and "*Ana Souza:*" not in html

    # Sem a assinatura, vai só o texto.
    canal.sign_messages = False
    db.commit()
    client.post(url, data={"csrf_token": token_csrf(client), "texto": "Pronto"})
    assert ponte.enviadas[-1][2] == "Pronto"

    r = client.post(url, data={"csrf_token": token_csrf(client), "texto": "   "})
    assert r.status_code == 422 and "Escreva a mensagem." in r.text


def test_envio_de_arquivos_vai_pela_fila_com_a_legenda_assinada(
    client: TestClient, db: Session, settings: Settings, ponte: PonteFalsa
) -> None:
    criar_usuario(db, "ana@x.com", nome="Ana", grupos={"Suporte": "member"})
    canal = _numero(db)
    _chega(settings, _msg(canal, "M1", "Oi"))
    chat = _conversa(db)
    entrar(client, "ana@x.com")
    r = client.post(
        f"/whatsapp/conversa/{chat.public_id}/enviar",
        data={"csrf_token": token_csrf(client), "texto": "Segue o orçamento"},
        files=[
            ("arquivos", ("orçamento.pdf", b"%PDF-1.7", "application/pdf")),
            ("arquivos", ("foto.png", b"\x89PNGfoto", "image/png")),
            ("arquivos", ("pagina.html", b"<script>alert(1)</script>", "text/html")),
        ],
    )
    assert r.status_code == 200
    pdf, foto, pagina = db.scalars(
        select(WhatsAppMessage).where(WhatsAppMessage.from_me).order_by(WhatsAppMessage.id)
    ).all()
    assert (pdf.kind, pdf.body, pdf.file_size) == ("document", "Segue o orçamento", 8)
    assert (foto.kind, foto.body, pagina.kind) == ("image", None, "document")
    assert all(m.status == "pending" for m in (pdf, foto, pagina))
    assert "orçamento.pdf" in r.text and f"/arquivo/{foto.id}" in r.text
    jobs = db.scalars(select(Job.args).where(Job.task == "whatsapp.send")).all()
    assert sorted(j["message_id"] for j in jobs) == [pdf.id, foto.id, pagina.id]

    # O arquivo do cliente que não é foto, vídeo ou áudio só baixa, nunca abre na tela.
    html = client.get(f"/whatsapp/conversa/{chat.public_id}/arquivo/{pagina.id}")
    assert html.headers["content-type"] == "application/octet-stream"
    assert html.headers["content-disposition"].startswith("attachment")

    async def enviar(sm: async_sessionmaker[AsyncSession]) -> None:
        async with sm() as s:
            for m in (pdf, foto):
                await service.retry_send(s, ponte, m.id)

    rodar(settings, enviar)
    primeiro, segundo = ponte.midias
    assert primeiro["caption"] == "*Ana:*\nSegue o orçamento"
    assert (primeiro["kind"], primeiro["file_name"]) == ("document", "orçamento.pdf")
    assert segundo["caption"] == "*Ana:*" and segundo["path"] == foto.media_path
    assert (settings.whatsapp_dir / "media" / segundo["path"]).read_bytes() == b"\x89PNGfoto"
    db.expire_all()
    assert pdf.status == "sent"

    # De outro grupo: o arquivo não abre.
    criar_usuario(db, "caio@x.com", nome="Caio", grupos={"Infra": "member"})
    caio = TestClient(client.app)
    caio.portal = client.portal
    entrar(caio, "caio@x.com")
    assert caio.get(f"/whatsapp/conversa/{chat.public_id}/arquivo/{foto.id}").status_code == 403


def test_disco_quase_cheio_recusa_o_arquivo(
    client: TestClient, db: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    criar_usuario(db, "ana@x.com", nome="Ana", grupos={"Suporte": "member"})
    canal = _numero(db)
    _chega(settings, _msg(canal, "M1", "Oi"))
    chat = _conversa(db)
    entrar(client, "ana@x.com")
    monkeypatch.setattr(service, "disk_ok", lambda _path: False)
    r = client.post(
        f"/whatsapp/conversa/{chat.public_id}/enviar",
        data={"csrf_token": token_csrf(client), "texto": ""},
        files=[("arquivos", ("a.pdf", b"x", "application/pdf"))],
    )
    assert r.status_code == 422 and "Espaço em disco insuficiente" in r.text
    assert db.scalar(select(WhatsAppMessage).where(WhatsAppMessage.from_me)) is None


def test_sem_a_ponte_a_mensagem_espera_na_fila(
    client: TestClient, db: Session, settings: Settings, ponte: PonteFalsa
) -> None:
    criar_usuario(db, "ana@x.com", nome="Ana", grupos={"Suporte": "member"})
    canal = _numero(db)
    _chega(settings, _msg(canal, "M1", "Oi"))
    chat = _conversa(db)
    entrar(client, "ana@x.com")
    ponte.fora = True
    r = client.post(
        f"/whatsapp/conversa/{chat.public_id}/enviar",
        data={"csrf_token": token_csrf(client), "texto": "Oi!"},
    )
    assert r.status_code == 200 and "Enviando" in r.text
    mensagem = db.scalar(select(WhatsAppMessage).where(WhatsAppMessage.from_me))
    assert mensagem is not None and mensagem.status == "pending"
    job = db.scalar(select(Job).where(Job.task == "whatsapp.send"))
    assert job is not None and job.args == {"message_id": mensagem.id}

    # A fila tenta de novo: com a ponte de volta, a mensagem sai.
    ponte.fora = False

    async def reenviar(sm: async_sessionmaker[AsyncSession]) -> None:
        async with sm() as s:
            await service.retry_send(s, ponte, mensagem.id)

    rodar(settings, reenviar)
    db.expire_all()
    assert mensagem.status == "sent" and ponte.enviadas[0][2] == "*Ana:*\nOi!"
