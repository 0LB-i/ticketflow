"""Configurações (idioma, cores, logotipo) e mensagens da API em inglês."""

import ast
import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from chamados.core.i18n import EN
from chamados.modules.audit.models import AuditLog
from chamados.modules.identity.passwords import password_problem
from tests.conftest import FakeMailer, criar_usuario, entrar

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
CORES = {"brand": "#1d4ed8", "neutral": "#64748B", "background": "#F8FAFC"}


def _admin(client: TestClient, db: Session) -> None:
    criar_usuario(db, "admin@x.com", "admin", nome="Admin")
    entrar(client, "admin@x.com")


def _data_url(tipo: str, dados: bytes) -> str:
    return f"data:{tipo};base64,{base64.b64encode(dados).decode()}"


def test_identidade_visual_e_publica(client: TestClient, db: Session) -> None:
    r = client.get("/api/v1/branding")
    assert r.status_code == 200
    assert r.json() == {
        "default_locale": "pt-BR",
        "colors": None,
        "logo_url": None,
        "report_logo_url": None,
    }


def test_so_admin_altera(client: TestClient, db: Session) -> None:
    criar_usuario(db, grupos={"TI": "supervisor"})
    entrar(client)
    assert client.patch("/api/v1/admin/settings", json={"colors": CORES}).status_code == 403
    r = client.put("/api/v1/admin/settings/logo", json={"data_url": _data_url("image/png", PNG)})
    assert r.status_code == 403
    assert client.delete("/api/v1/admin/settings/logo").status_code == 403
    r = client.put(
        "/api/v1/admin/settings/report-logo", json={"data_url": _data_url("image/png", PNG)}
    )
    assert r.status_code == 403
    assert client.delete("/api/v1/admin/settings/report-logo").status_code == 403


def test_idioma_e_cores(client: TestClient, db: Session) -> None:
    _admin(client, db)
    r = client.patch("/api/v1/admin/settings", json={"default_locale": "en", "colors": CORES})
    assert r.json()["default_locale"] == "en"
    assert r.json()["colors"] == {"brand": "#1D4ED8", "neutral": "#64748B", "background": "#F8FAFC"}
    assert client.get("/api/v1/branding").json()["colors"]["brand"] == "#1D4ED8"

    # Cor nula volta ao padrão; idioma fora da lista e cor malformada são recusados
    assert client.patch("/api/v1/admin/settings", json={"colors": None}).json()["colors"] is None
    assert client.patch("/api/v1/admin/settings", json={"default_locale": "fr"}).status_code == 422
    r = client.patch("/api/v1/admin/settings", json={"colors": {**CORES, "brand": "laranja"}})
    assert r.status_code == 422

    mudancas = db.scalars(
        select(AuditLog).where(AuditLog.action == "settings.updated").order_by(AuditLog.id)
    ).all()
    assert [m.after for m in mudancas] == [
        {
            "locale": "en",
            "colors": {"brand": "#1D4ED8", "neutral": "#64748B", "background": "#F8FAFC"},
        },
        {"colors": None},
    ]


def test_logotipo(client: TestClient, db: Session) -> None:
    _admin(client, db)
    url = "/api/v1/admin/settings/logo"
    svg = _data_url("image/svg+xml", b"<svg onload='alert(1)'/>")
    assert client.put(url, json={"data_url": svg}).status_code == 422
    # Tipo declarado não bate com o conteúdo
    assert client.put(url, json={"data_url": _data_url("image/jpeg", PNG)}).status_code == 422
    grande = _data_url("image/png", PNG + b"\0" * 256 * 1024)
    assert client.put(url, json={"data_url": grande}).status_code == 422

    r = client.put(url, json={"data_url": _data_url("image/png", PNG)})
    logo_url = r.json()["logo_url"]
    assert logo_url.startswith("/api/v1/branding/logo?v=")
    client.cookies.clear()  # o logotipo aparece também na tela de login
    imagem = client.get(logo_url)
    assert imagem.content == PNG
    assert imagem.headers["content-type"] == "image/png"
    assert "immutable" in imagem.headers["cache-control"]

    entrar(client, "admin@x.com")
    assert client.delete(url).json()["logo_url"] is None
    assert client.get("/api/v1/branding/logo").status_code == 404
    assert client.delete(url).status_code == 404


def test_logotipo_dos_relatorios(client: TestClient, db: Session) -> None:
    """O logotipo dos PDFs de relatório é outro, separado do logotipo do aplicativo."""
    _admin(client, db)
    url = "/api/v1/admin/settings/report-logo"
    assert client.put(url, json={"data_url": _data_url("image/jpeg", PNG)}).status_code == 422
    r = client.put(url, json={"data_url": _data_url("image/png", PNG)})
    assert r.json()["logo_url"] is None  # o do aplicativo continua sem
    report_logo_url = r.json()["report_logo_url"]
    assert report_logo_url.startswith("/api/v1/branding/report-logo?v=")
    assert client.get(report_logo_url).content == PNG
    assert client.get("/api/v1/branding/logo").status_code == 404
    assert client.delete(url).json()["report_logo_url"] is None
    assert client.get("/api/v1/branding/report-logo").status_code == 404
    assert client.delete(url).status_code == 404


def test_idioma_do_usuario(client: TestClient, db: Session) -> None:
    criar_usuario(db)
    entrar(client)
    assert client.get("/api/v1/me").json()["locale"] is None
    assert client.patch("/api/v1/me", json={"locale": "en"}).json()["locale"] == "en"
    assert client.patch("/api/v1/me", json={"locale": "xx"}).status_code == 422
    assert client.patch("/api/v1/me", json={"locale": None}).json()["locale"] is None


def test_erros_em_ingles(client: TestClient, db: Session) -> None:
    criar_usuario(db)
    entrar(client)
    r = client.get("/api/v1/tickets/999999", headers={"Accept-Language": "en-US,en;q=0.9"})
    assert r.json()["title"] == "Not found"
    assert r.json()["detail"] == "Ticket not found."
    r = client.get("/api/v1/tickets/999999", headers={"Accept-Language": "pt-BR"})
    assert r.json()["detail"] == "Chamado não encontrado."


def test_emails_no_idioma_da_pessoa(client: TestClient, db: Session, mailer: FakeMailer) -> None:
    _admin(client, db)
    client.patch("/api/v1/admin/settings", json={"default_locale": "en"})
    bia = criar_usuario(db, "bia@x.com", nome="Bia Lima", senha=None)
    client.post(f"/api/v1/users/{bia.public_id}/link")
    assert mailer.sent[-1][1] == "Your TicketFlow access"
    assert mailer.sent[-1][2].startswith("Hello, Bia.")


# --- todo texto de erro da API tem tradução ---------------------------------------------------

SRC = Path(__file__).parents[2] / "src" / "chamados"
# Mensagens montadas fora da chamada (constantes e variáveis), conferidas abaixo.
NAO_LITERAIS = {"INVALID", "FORBIDDEN", "INVALID_LOGO", "problem", "message"}
# Erro interno de configuração: não chega a quem usa o sistema.
SEM_TRADUCAO = {"Status padrão do tipo {kind} não configurado."}


class _Constantes(dict[str, object]):
    def __missing__(self, nome: str) -> str:
        return "{" + nome + "}"


def _mensagens() -> set[str]:
    achadas: set[str] = set()
    for arquivo in SRC.rglob("*.py"):
        arvore = ast.parse(arquivo.read_text())
        constantes = {
            alvo.id: no.value.value
            for no in arvore.body
            if isinstance(no, ast.Assign) and isinstance(no.value, ast.Constant)
            for alvo in no.targets
            if isinstance(alvo, ast.Name)
        }
        # Mensagens num dicionário do módulo (ex.: INACTIVE em tickets/service.py).
        dicionarios = {
            alvo.id: [str(v.value) for v in no.value.values if isinstance(v, ast.Constant)]
            for no in arvore.body
            if isinstance(no, ast.Assign) and isinstance(no.value, ast.Dict)
            for alvo in no.targets
            if isinstance(alvo, ast.Name)
        }
        for no in ast.walk(arvore):
            if isinstance(no, ast.Call) and getattr(no.func, "id", None) == "required_text":
                achadas.add(ast.literal_eval(no.args[1]))
            if not (isinstance(no, ast.Call) and getattr(no.func, "id", None) == "HTTPException"):
                continue
            if len(no.args) < 2:
                continue
            arg = no.args[1]
            if isinstance(arg, ast.Constant):
                achadas.add(str(arg.value))
            elif isinstance(arg, ast.Name) and arg.id in constantes:
                achadas.add(str(constantes[arg.id]))
            elif isinstance(arg, ast.Subscript) and getattr(arg.value, "id", None) in dicionarios:
                achadas.update(dicionarios[arg.value.id])  # type: ignore[attr-defined]
            elif isinstance(arg, ast.JoinedStr):
                # f-string: monta com as constantes do módulo; variáveis ficam como {nome}.
                valores = _Constantes(constantes)
                achadas.add(eval(ast.unparse(arg), {}, valores))  # noqa: S307
            else:
                assert isinstance(arg, ast.Name) and arg.id in NAO_LITERAIS, ast.unparse(arg)
    return achadas


def test_toda_mensagem_de_erro_tem_traducao() -> None:
    mensagens = _mensagens()
    assert "Chamado não encontrado." in mensagens  # achou o código (com SRC errado, nada falta)
    faltando = {m for m in mensagens if m not in EN} - SEM_TRADUCAO
    assert not faltando


@pytest.mark.parametrize("senha", ["curta", "x" * 300, "12345678", "ana@exemplo.com"])
def test_mensagens_de_senha_tem_traducao(senha: str) -> None:
    problema = password_problem(senha, "ana@exemplo.com")
    assert problema in EN
