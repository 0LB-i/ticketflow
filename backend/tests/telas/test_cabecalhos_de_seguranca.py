"""Permissions-Policy e Cross-Origin-Opener-Policy em todas as respostas (core/security_headers)."""

from typing import Any

from fastapi.testclient import TestClient

from chamados.core.security_headers import HEADERS
from chamados.web.templating import static
from tests.apoio import anexo


def test_cabecalhos_em_telas_api_static_e_anexos(
    client: TestClient, cenario: dict[str, Any]
) -> None:
    respostas = {
        "tela": client.get("/chamados"),
        "api": client.get("/api/v1/me"),
        "static": client.get(static("favicon.svg")),
        "anexo": client.get(f"/api/v1/attachments/{anexo(client)}"),
    }
    for onde, r in respostas.items():
        assert r.status_code == 200, onde
        for nome, valor in HEADERS.items():
            assert r.headers[nome] == valor, onde
