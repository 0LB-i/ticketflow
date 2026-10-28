"""Tela do servidor da Empresa: os dados da empresa e os logotipos (ADR 0011)."""

import re
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from chamados.modules.system.models import SystemSetting
from tests.conftest import criar_usuario, entrar

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
URL = "/admin/empresa"
DADOS = {
    "name": "Padaria Pão Quente Ltda",
    "document": "11.222.333/0001-81",
    "phone": "(11) 3333-4444",
    "postal_code": "01310-100",
    "city": "São Paulo",
    "state": "SP",
}


def _form(client: TestClient, **dados: Any) -> dict[str, Any]:
    return {"csrf_token": client.cookies["tf_csrf"], **dados}


def _aviso(html: str) -> str:
    achado = re.search(r'data-aviso="\w+".*?<p class="font-semibold">(.*?)</p>', html, re.S)
    return achado.group(1) if achado else ""


def _admin(client: TestClient, db: Session) -> None:
    criar_usuario(db, "admin@exemplo.com", "admin", nome="Admin")
    entrar(client, "admin@exemplo.com")


def _valor(db: Session, chave: str) -> Any:
    db.expire_all()
    return db.scalar(select(SystemSetting.value).where(SystemSetting.key == chave))


def test_so_admin(client: TestClient, db: Session) -> None:
    criar_usuario(db, grupos={"TI": "supervisor"})
    entrar(client)
    assert client.get(URL).status_code == 403
    assert client.post(URL, data=_form(client, **DADOS)).status_code == 403
    arquivo = {"logo": ("logo.png", PNG, "image/png")}
    assert client.post(f"{URL}/logo", data=_form(client), files=arquivo).status_code == 403
    assert 'href="/admin/empresa"' not in client.get("/chamados").text
    assert _valor(db, "company") is None


def test_dados_da_empresa(client: TestClient, db: Session) -> None:
    """Os erros aparecem todos de uma vez, com o que foi digitado; salvar grava e volta com os
    dados formatados."""
    _admin(client, db)
    r = client.get(URL)
    assert r.status_code == 200 and 'href="/admin/empresa" class' in r.text  # no menu
    r = client.post(
        URL,
        data=_form(client, name="", document="11.222.333/0001-82", phone="123", postal_code="1"),
    )
    assert r.status_code == 422
    assert "Campo obrigatório." in r.text and "CNPJ inválido." in r.text
    assert "Informe o DDD e o número." in r.text and "O CEP tem 8 números." in r.text
    assert 'value="11.222.333/0001-82"' in r.text
    assert _valor(db, "company") is None
    r = client.post(URL, data=_form(client, **DADOS), follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == URL
    r = client.get(URL)
    assert _aviso(r.text) == "Alterações salvas"
    assert 'value="11.222.333/0001-81"' in r.text and 'value="(11) 3333-4444"' in r.text
    assert 'value="01310-100"' in r.text
    empresa = _valor(db, "company")
    assert (empresa["document"], empresa["phone"], empresa["website"]) == (
        "11222333000181", "1133334444", None
    )  # fmt: skip


def test_logotipo(client: TestClient, db: Session) -> None:
    _admin(client, db)
    envio = _form(client)
    r = client.post(f"{URL}/logo", data=envio, files={"logo": ("logo.gif", b"GIF89a", "image/gif")})
    assert _aviso(r.text) == "Envie uma imagem PNG, JPEG ou WebP."
    grande = PNG + b"\0" * 256 * 1024
    r = client.post(f"{URL}/logo", data=envio, files={"logo": ("logo.png", grande, "image/png")})
    assert _aviso(r.text) == "A imagem passa de 256 KB."
    r = client.post(f"{URL}/logo", data=envio, files={"logo": ("logo.png", PNG, "image/png")})
    assert _aviso(r.text) == "Logotipo atualizado"
    assert '<img src="/api/v1/branding/logo?v=' in r.text
    r = client.post(f"{URL}/logo/remover", data=envio)
    assert _aviso(r.text) == "Logotipo removido"
    assert _valor(db, "logo") is None


def test_logotipo_dos_relatorios(client: TestClient, db: Session) -> None:
    """Uma seção própria, separada do logotipo do aplicativo, com as mesmas regras."""
    _admin(client, db)
    envio = _form(client)
    r = client.get(URL)
    assert 'id="logotipo-relatorios"' in r.text and "Sem logotipo: os PDFs saem" in r.text
    arquivo = {"logo": ("logo.gif", b"GIF89a", "image/gif")}
    r = client.post(f"{URL}/logo-relatorios", data=envio, files=arquivo)
    assert _aviso(r.text) == "Envie uma imagem PNG, JPEG ou WebP."
    arquivo = {"logo": ("logo.png", PNG, "image/png")}
    r = client.post(f"{URL}/logo-relatorios", data=envio, files=arquivo)
    assert _aviso(r.text) == "Logotipo atualizado"
    assert '<img src="/api/v1/branding/report-logo?v=' in r.text
    assert _valor(db, "logo") is None and _valor(db, "report_logo")
    r = client.post(f"{URL}/logo-relatorios/remover", data=envio)
    assert _aviso(r.text) == "Logotipo removido"
    assert _valor(db, "report_logo") is None
