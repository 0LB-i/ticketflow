from fastapi.testclient import TestClient

from chamados.config import Settings
from chamados.main import create_app


def test_health_ok(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["database"].startswith("PostgreSQL 1")


def test_health_sem_banco(settings: Settings) -> None:
    sem_banco = settings.model_copy(
        update={"database_url": "postgresql+psycopg://x:x@127.0.0.1:1/nada"}
    )
    with TestClient(create_app(sem_banco)) as c:
        r = c.get("/api/health")
    assert r.status_code == 503
    assert r.headers["content-type"] == "application/problem+json"
    assert r.json()["detail"] == "Banco de dados indisponível"
