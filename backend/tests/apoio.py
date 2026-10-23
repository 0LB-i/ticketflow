"""Auxiliares usados por testes de mais de uma pasta (os de uma pasta só ficam no próprio arquivo).

O cenário Ana e Bia (supervisora) no TI, Caio na Infra, é a fixture `cenario` do conftest.
"""

import asyncio
import re
from collections.abc import Awaitable, Callable
from datetime import date, datetime, time, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from chamados.config import Settings
from chamados.db.engine import create_engine
from chamados.db.session import make_sessionmaker
from chamados.modules.identity.models import User
from chamados.modules.identity.tokens import new_api_token
from chamados.modules.reports.service import TZ

API = "/api/v1/tickets"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32

# --- chamados ---------------------------------------------------------------------------------


def base(c: dict[str, Any]) -> dict[str, Any]:
    """O que todo chamado precisa: cliente e responsável."""
    return {"client_id": c["cliente"], "assignee": "me"}


def registrar(client: TestClient, c: dict[str, Any], **extra: Any) -> dict[str, Any]:
    dados = {**base(c), "title": "Impressora não imprime", "category_id": c["impressao"], **extra}
    r = client.post(API, json=dados)
    assert r.status_code == 201, r.text
    result: dict[str, Any] = r.json()
    return result


def eventos(client: TestClient, numero: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = client.get(f"{API}/{numero}/events").json()["items"]
    return result


def enviar(client: TestClient, nome: str, conteudo: bytes) -> Any:
    return client.post(
        "/api/v1/uploads", files={"file": (nome, conteudo, "application/x-qualquer")}
    )


def anexo(client: TestClient, nome: str = "print.png", conteudo: bytes = PNG) -> str:
    r = enviar(client, nome, conteudo)
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


# --- tokens de API ----------------------------------------------------------------------------


def criar_token(
    db: Session, email: str, scope: str = "write", expires_at: datetime | None = None
) -> str:
    user = db.scalar(select(User).where(User.email == email))
    assert user is not None
    raw, token = new_api_token(user, "Teste", scope, expires_at)
    db.add(token)
    db.commit()
    return raw


def com_token(client: TestClient, raw: str) -> TestClient:
    """Só o token: sem o cookie da sessão nem o header CSRF."""
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    client.headers["Authorization"] = f"Bearer {raw}"
    return client


# --- worker -----------------------------------------------------------------------------------


def rodar[T](
    settings: Settings, fn: Callable[[async_sessionmaker[AsyncSession]], Awaitable[T]]
) -> T:
    """Roda `fn` com um sessionmaker assíncrono, como o worker faz."""

    async def main() -> T:
        engine = create_engine(settings.database_url)
        try:
            return await fn(make_sessionmaker(engine))
        finally:
            await engine.dispose()

    return asyncio.run(main())


# --- relatórios -------------------------------------------------------------------------------


def em(dia: date, hora: int, minuto: int = 0) -> datetime:
    return datetime.combine(dia, time(hora, minuto), TZ)


def dia_util_passado() -> date:
    """Uma segunda-feira da semana passada (tarefas não podem ser no futuro)."""
    hoje = datetime.now(TZ).date()
    return hoje - timedelta(days=hoje.weekday() + 7)


def tarefa(client: TestClient, numero: int, minutos: int, fim: datetime) -> None:
    r = client.post(
        f"{API}/{numero}/comments",
        json={"body": "Feito", "time_spent_minutes": minutos, "done_at": fim.isoformat()},
    )
    assert r.status_code == 201, r.text


# --- cadastros --------------------------------------------------------------------------------

NOVO_USUARIO = {
    "email": "bruno@exemplo.com",
    "username": "bruno",
    "full_name": "Bruno Lima",
    "display_name": "Bruno",
    "role": "agent",
    "password": "Provisoria#2026",
}
ENDERECO = {
    "postal_code": "01310-100",
    "street": "Avenida Paulista",
    "number": "1000",
    "complement": "Conjunto 12",
    "district": "Bela Vista",
    "city": "São Paulo",
    "state": "sp",
}
PESSOA = {
    "kind": "person",
    "name": "João da Silva",
    "document": "529.982.247-25",
    "id_number": "123456789",
    "birth_date": "1985-04-12",
    "emails": ["Joao@Exemplo.com", "joao@exemplo.com", "joao.silva@exemplo.com"],
    "phones": ["(11) 3333-4444", "+55 11 98765-4321"],
    **ENDERECO,
}
EMPRESA = {
    "kind": "company",
    "name": "Padaria Pão Quente Ltda",
    "trade_name": "Pão Quente",
    "document": "12.ABC.345/01DE-35",  # CNPJ alfanumérico
    "state_registration": "isento",
    "municipal_registration": "1234567",
    "contact_name": "Maria",
    "emails": ["contato@paoquente.com.br"],
    "phones": ["1133334444"],
    **ENDERECO,
}

# --- telas ------------------------------------------------------------------------------------


def formulario(client: TestClient, **dados: Any) -> dict[str, Any]:
    """Os campos de um formulário das telas, com o token CSRF."""
    return {"csrf_token": client.cookies["tf_csrf"], **dados}


def aviso(client: TestClient, numero: int, html: str | None = None) -> str:
    """O texto do aviso que a tela do chamado mostra depois de uma ação (a resposta da ação,
    que já seguiu o redirecionamento, ou a próxima visita ao chamado)."""
    html = html if html is not None else client.get(f"/chamados/{numero}").text
    achado = re.search(r'data-aviso="\w+".*?<p class="font-semibold">(.*?)</p>', html, re.S)
    return achado.group(1) if achado else ""


def status_id(client: TestClient, nome: str) -> str:
    return str(
        next(s["id"] for s in client.get("/api/v1/statuses").json()["items"] if s["name"] == nome)
    )
