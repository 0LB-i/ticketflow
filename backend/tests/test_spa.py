"""A SPA compilada é servida pelo uvicorn na mesma origem da API (ADR 0010)."""

from pathlib import Path

from fastapi.testclient import TestClient

from chamados.config import Settings
from chamados.main import create_app


def _dist(tmp: Path) -> Path:
    (tmp / "assets").mkdir()
    (tmp / "index.html").write_text("<div id=app></div>")
    (tmp / "assets" / "app.js").write_text("console.log(1)")
    (tmp / "favicon.svg").write_text("<svg/>")
    return tmp


def test_spa_e_rotas_do_frontend(settings: Settings, tmp_path: Path) -> None:
    app = create_app(settings.model_copy(update={"frontend_dist": _dist(tmp_path)}))
    with TestClient(app) as c:
        assert c.get("/relatorios").text == "<div id=app></div>"
        assert c.get("/admin/configuracoes").text == "<div id=app></div>"
        assert c.get("/assets/app.js").text == "console.log(1)"
        assert "immutable" in c.get("/assets/app.js").headers["cache-control"]
        assert c.get("/relatorios").headers["cache-control"] == "no-cache"
        assert c.get("/favicon.svg").text == "<svg/>"
        assert c.get("/../../etc/passwd").text == "<div id=app></div>"
        assert c.get("/api/nao-existe").status_code == 404


def test_sem_frontend_compilado_so_a_api(client: TestClient) -> None:
    assert client.get("/relatorios").status_code == 404
