"""Erros seguem a RFC 9457 (docs/05)."""

from fastapi import FastAPI, Query
from fastapi.testclient import TestClient

from chamados.core.errors import register_error_handlers


def test_rota_api_inexistente_da_404_em_problem_json(client: TestClient) -> None:
    r = client.get("/api/nao-existe")
    assert r.status_code == 404
    assert r.headers["content-type"] == "application/problem+json"
    assert r.json() == {"type": "about:blank", "title": "Não encontrado", "status": 404}


def test_sem_swagger_mas_com_a_especificacao(client: TestClient) -> None:
    """O Swagger carregava scripts de uma CDN na mesma origem das telas: fica desligado."""
    assert client.get("/api/docs").status_code == 404
    assert client.get("/api/openapi.json").status_code == 200


def _app_de_teste() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/soma")
    def soma(a: int = Query(), b: int = Query()) -> int:
        return a + b

    @app.get("/quebra")
    def quebra() -> None:
        raise RuntimeError("falha inesperada")

    return app


def test_validacao_lista_os_campos() -> None:
    r = TestClient(_app_de_teste()).get("/soma?a=1&b=x")
    assert r.status_code == 422
    body = r.json()
    assert body["title"] == "Dados inválidos"
    assert [e["loc"] for e in body["errors"]] == [["query", "b"]]


def test_erro_inesperado_nao_vaza_detalhes() -> None:
    r = TestClient(_app_de_teste(), raise_server_exceptions=False).get("/quebra")
    assert r.status_code == 500
    assert r.json() == {"type": "about:blank", "title": "Erro interno", "status": 500}
