"""Telas do servidor de login, senha esquecida, redefinição e troca de senha (ADR 0011)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from chamados.modules.system.models import SystemSetting
from tests.conftest import SENHA, FakeMailer, criar_usuario


def _entrar(client: TestClient, volta: str = "/chamados", senha: str = SENHA) -> str:
    r = client.post(
        "/login",
        data={"login": "ana@exemplo.com", "senha": senha, "volta": volta},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    return r.headers["location"]


def test_tela_de_login(client: TestClient) -> None:
    r = client.get("/login")
    assert r.status_code == 200
    assert '<html lang="pt-BR">' in r.text
    assert "<title>Entrar · TicketFlow</title>" in r.text
    assert 'name="senha"' in r.text
    assert "tf-cores" not in r.text  # cores padrão: só os tokens do CSS


def test_login_abre_a_sessao_e_volta_para_a_pagina_pedida(client: TestClient, db: Session) -> None:
    criar_usuario(db)
    assert _entrar(client, volta="/chamados/1234") == "/chamados/1234"
    assert client.get("/api/v1/me").status_code == 200
    # Logado, a tela de login manda adiante.
    r = client.get("/login?volta=/relatorios", follow_redirects=False)
    assert r.headers["location"] == "/relatorios"


def test_login_nao_volta_para_outro_site(client: TestClient, db: Session) -> None:
    criar_usuario(db)
    assert _entrar(client, volta="//outro.site/x") == "/chamados"
    client.cookies.clear()
    assert _entrar(client, volta="https://outro.site") == "/chamados"
    client.cookies.clear()
    assert _entrar(client, volta="/\\outro.site") == "/chamados"


def test_login_recusa_envio_de_outro_site(client: TestClient, db: Session) -> None:
    criar_usuario(db)
    dados = {"login": "ana@exemplo.com", "senha": SENHA}
    r = client.post("/login", data=dados, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    assert r.headers["content-type"].startswith("text/html")
    assert "tf_sessao" not in client.cookies


def test_login_com_senha_errada_mostra_o_erro(client: TestClient, db: Session) -> None:
    criar_usuario(db)
    r = client.post("/login", data={"login": "ana@exemplo.com", "senha": "errada"})
    assert r.status_code == 401
    assert "E-mail ou senha inválidos." in r.text
    assert 'value="ana@exemplo.com"' in r.text  # o login digitado continua no campo
    assert "tf_sessao" not in client.cookies


def test_tela_no_idioma_padrao_do_sistema(client: TestClient, db: Session) -> None:
    db.add(SystemSetting(key="locale", value="en"))
    db.commit()
    r = client.post("/login", data={"login": "ninguem", "senha": "x"})
    assert '<html lang="en">' in r.text
    assert "Invalid email or password." in r.text


def test_cores_personalizadas_no_html(client: TestClient, db: Session) -> None:
    cores = {"brand": "#2563EB", "neutral": "#64748B", "background": "#FFFFFF"}
    db.add(SystemSetting(key="colors", value=cores))
    db.commit()
    r = client.get("/login")
    assert '<style id="tf-cores">html:root{--tf-brand:#2563EB;' in r.text


def test_sair_exige_o_token_csrf(client: TestClient, db: Session) -> None:
    criar_usuario(db)
    _entrar(client)
    r = client.post("/sair", data={"csrf_token": "outro"})
    assert r.status_code == 403
    # Uma página, não o JSON da API (ex.: o token de uma aba antiga).
    assert r.headers["content-type"].startswith("text/html")
    assert "<title>Acesso negado · TicketFlow</title>" in r.text
    r = client.post("/sair", data={"csrf_token": client.cookies["tf_csrf"]}, follow_redirects=False)
    assert r.headers["location"] == "/login"
    assert client.get("/api/v1/me").status_code == 401


def test_esqueci_a_senha_responde_igual(
    client: TestClient, db: Session, mailer: FakeMailer
) -> None:
    criar_usuario(db)
    for email in ("ninguem@exemplo.com", "nao-e-email", "ana@exemplo.com"):
        r = client.post("/esqueci-senha", data={"email": email})
        assert r.status_code == 200
        assert "Se o e-mail estiver cadastrado" in r.text
    assert len(mailer.sent) == 1


def test_redefinir_senha_pela_tela(client: TestClient, db: Session, mailer: FakeMailer) -> None:
    criar_usuario(db)
    client.post("/esqueci-senha", data={"email": "ana@exemplo.com"})
    caminho = mailer.last_link().removeprefix("http://teste")
    token = caminho.rsplit("/", 1)[1]

    r = client.get(caminho)
    assert r.status_code == 200
    assert "Para Ana Souza (ana@exemplo.com)" in r.text
    # O link de redefinição não serve de convite.
    assert client.get(f"/convite/{token}").status_code == 404

    diferente = {"senha": "nova senha bem longa", "confirmar": "outra senha bem longa"}
    r = client.post(caminho, data=diferente)
    assert r.status_code == 422
    assert "As duas senhas não são iguais." in r.text
    r = client.post(caminho, data={"senha": "curta", "confirmar": "curta"})
    assert r.status_code == 422
    assert "pelo menos 8 caracteres" in r.text

    nova = {"senha": "nova senha bem longa", "confirmar": "nova senha bem longa"}
    r = client.post(caminho, data=nova, follow_redirects=False)
    assert r.headers["location"] == "/login?aviso=senha-criada"
    assert "Senha criada." in client.get("/login?aviso=senha-criada").text
    assert client.post(caminho, data=nova).status_code == 404  # uso único
    _entrar(client, senha="nova senha bem longa")


def test_troca_obrigatoria_da_senha_provisoria(client: TestClient, db: Session) -> None:
    user = criar_usuario(db, trocar_senha=True)
    r = client.get("/trocar-senha", follow_redirects=False)
    assert r.headers["location"] == "/login?volta=%2Ftrocar-senha"

    _entrar(client)
    assert client.get("/trocar-senha").status_code == 200
    csrf = client.cookies["tf_csrf"]
    nova = {"senha": "nova senha bem longa", "confirmar": "nova senha bem longa"}
    assert client.post("/trocar-senha", data={**nova, "csrf_token": "x"}).status_code == 403
    r = client.post("/trocar-senha", data={**nova, "confirmar": "outra", "csrf_token": csrf})
    assert r.status_code == 422

    r = client.post("/trocar-senha", data={**nova, "csrf_token": csrf}, follow_redirects=False)
    assert r.headers["location"] == "/chamados"
    assert "Senha trocada" in client.get("/chamados").text
    db.refresh(user)
    assert not user.must_change_password
    # Depois da troca, a tela não abre mais.
    assert client.get("/trocar-senha", follow_redirects=False).headers["location"] == "/chamados"


def test_arquivos_estaticos(client: TestClient) -> None:
    r = client.get("/static/js/app.js")
    assert r.status_code == 200
    assert "tf-tema" in r.text


def test_paginas_com_sessao_nao_ficam_no_navegador(client: TestClient, db: Session) -> None:
    assert "cache-control" not in client.get("/login").headers
    criar_usuario(db, grupos={"TI": "member"})
    _entrar(client)
    r = client.get("/chamados")
    assert r.headers["cache-control"] == "no-store"
    assert '"historyCacheSize": 0' in r.text  # o HTMX não guarda páginas no sessionStorage
