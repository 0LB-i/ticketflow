"""Meu perfil (/perfil): nome de exibição, cargo, telefone, a foto e a troca da senha."""

import io
import re
from typing import Any

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from chamados.modules.identity.models import User
from tests.api.test_papel_cliente import usuario_cliente
from tests.conftest import SENHA, criar_cliente, criar_usuario, entrar, outra_sessao, token_csrf

URL = "/perfil"


def _form(client: TestClient, **dados: Any) -> dict[str, Any]:
    return {"csrf_token": token_csrf(client), **dados}


def _aviso(html: str) -> str:
    achado = re.search(r'data-aviso="\w+".*?<p class="font-semibold">(.*?)</p>', html, re.S)
    return achado.group(1) if achado else ""


def _usuario(db: Session) -> User:
    db.expire_all()
    user = db.scalar(select(User).where(User.email == "ana@exemplo.com"))
    assert user is not None
    return user


def _imagem(formato: str, tamanho: tuple[int, int] = (600, 400)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", tamanho, "red").save(out, formato)
    return out.getvalue()


def test_menu_leva_ao_perfil(client: TestClient, db: Session) -> None:
    criar_usuario(db, grupos={"TI": "supervisor"})
    entrar(client)
    html = client.get("/chamados").text
    assert 'href="/perfil" role="menuitem"' in html
    html = client.get(URL).text
    assert "Meu perfil" in html and "Ana Souza" in html and "ana@exemplo.com" in html
    assert "TI" in html and "(supervisor)" in html and "Agente" in html


def test_salvar_os_dados(client: TestClient, db: Session) -> None:
    """Os erros aparecem todos de uma vez, com o que foi digitado; salvar grava o telefone só
    com os dígitos e o nome novo aparece no menu."""
    criar_usuario(db)
    entrar(client)
    r = client.post(URL, data=_form(client, display_name=" ", job_title="Analista", phone="123"))
    assert r.status_code == 422
    assert "Campo obrigatório." in r.text and "Informe o DDD e o número." in r.text
    assert 'value="Analista"' in r.text
    assert _usuario(db).job_title is None
    dados = {"display_name": " Aninha ", "job_title": "Analista de suporte"}
    dados["phone"] = "(11) 98765-4321"
    r = client.post(URL, data=_form(client, **dados), follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == URL
    r = client.get(URL)
    assert _aviso(r.text) == "Alterações salvas"
    assert 'value="(11) 98765-4321"' in r.text and "Aninha" in client.get("/chamados").text
    user = _usuario(db)
    assert (user.display_name, user.job_title, user.phone) == (
        "Aninha", "Analista de suporte", "11987654321"
    )  # fmt: skip
    client.post(URL, data=_form(client, display_name="Ana", job_title="", phone=""))
    user = _usuario(db)
    assert (user.display_name, user.job_title, user.phone) == ("Ana", None, None)


def test_patch_me_muda_so_o_que_vem(client: TestClient, db: Session) -> None:
    criar_usuario(db)
    entrar(client)
    client.patch("/api/v1/me", json={"locale": "en"})
    r = client.patch("/api/v1/me", json={"phone": "+55 (21) 3333-4444", "job_title": "Gerente"})
    assert r.status_code == 200
    assert (r.json()["locale"], r.json()["phone"], r.json()["job_title"]) == (
        "en", "2133334444", "Gerente"
    )  # fmt: skip
    assert client.patch("/api/v1/me", json={"phone": "123"}).status_code == 422
    assert client.patch("/api/v1/me", json={"display_name": None}).status_code == 422
    assert client.patch("/api/v1/me", json={"display_name": "A"}).status_code == 422


def test_foto(client: TestClient, db: Session) -> None:
    """A foto vira um WebP 256×256; o menu mostra a imagem no lugar da inicial."""
    criar_usuario(db)
    entrar(client)
    arquivo = {"foto": ("eu.jpg", _imagem("JPEG"), "image/jpeg")}
    r = client.post(f"{URL}/foto", data=_form(client), files=arquivo, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == URL
    assert _aviso(client.get(URL).text) == "Foto atualizada"
    user = _usuario(db)
    assert user.avatar_hash and user.avatar
    assert f'src="/perfil/foto?v={user.avatar_hash}"' in client.get("/chamados").text
    r = client.get(f"{URL}/foto?v={user.avatar_hash}")
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    assert "immutable" in r.headers["cache-control"]
    with Image.open(io.BytesIO(r.content)) as foto:
        assert (foto.format, foto.size) == ("WEBP", (256, 256))
    # Outra pessoa não vê esta foto pelo endereço: a rota só devolve a de quem pede.
    criar_usuario(db, "bia@exemplo.com", nome="Bia")
    bia = outra_sessao(client)
    entrar(bia, "bia@exemplo.com")
    assert bia.get(f"{URL}/foto").status_code == 404

    r = client.post(f"{URL}/foto/remover", data=_form(client), follow_redirects=False)
    assert r.status_code == 303
    assert _aviso(client.get(URL).text) == "Foto removida"
    assert _usuario(db).avatar_hash is None
    assert client.get(f"{URL}/foto").status_code == 404


def test_foto_invalida(client: TestClient, db: Session) -> None:
    criar_usuario(db)
    entrar(client)
    falsa = {"foto": ("eu.png", b"\x89PNG\r\n\x1a\n" + b"\0" * 32, "image/png")}
    r = client.post(f"{URL}/foto", data=_form(client), files=falsa)
    assert _aviso(r.text) == "Foto inválida: envie uma imagem PNG, JPEG ou WebP."
    gif = {"foto": ("eu.gif", _imagem("GIF"), "image/gif")}
    r = client.post(f"{URL}/foto", data=_form(client), files=gif)
    assert _aviso(r.text) == "Envie uma imagem PNG, JPEG ou WebP."
    assert _usuario(db).avatar_hash is None


def test_trocar_a_senha(client: TestClient, db: Session) -> None:
    criar_usuario(db)
    entrar(client)
    nova = "outra senha longa de teste"
    r = client.post(f"{URL}/senha", data=_form(client, atual="errada", senha=nova, confirmar=nova))
    assert r.status_code == 422 and "A senha atual não confere." in r.text
    r = client.post(f"{URL}/senha", data=_form(client, atual=SENHA, senha=nova, confirmar="x"))
    assert r.status_code == 422 and "As duas senhas não são iguais." in r.text
    r = client.post(
        f"{URL}/senha",
        data=_form(client, atual=SENHA, senha=nova, confirmar=nova),
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"] == URL
    assert _aviso(client.get(URL).text) == "Senha trocada"
    outro = outra_sessao(client)
    entrar(outro, senha=nova)


def test_papel_cliente_abre_o_perfil(client: TestClient, db: Session) -> None:
    usuario_cliente(db, criar_cliente(db, "Padaria", "11222333000181"))
    entrar(client, "cli@x.com")
    r = client.get(URL, follow_redirects=False)
    assert r.status_code == 200 and "Meu perfil" in r.text
