"""`Idempotency-Key` nos POST com token de API (docs/05).

Um agente que repete a chamada depois de um timeout não registra o chamado duas vezes: a primeira
resposta de sucesso fica guardada e volta igual (com `Idempotent-Replayed: true`) para a mesma
chave do mesmo token, sem executar de novo. A chave é opcional e vale por pelo menos 24 h (a
rotina `jobs.cleanup` apaga as mais antigas).

- Mesma chave com outra requisição (método, caminho ou corpo): 422.
- A primeira ainda em andamento: 409. Se ela parou há mais de 5 min (o processo caiu), a nova
  assume a chave.
- Erro (4xx ou 5xx): nada fica guardado, e a mesma chave pode ser usada de novo.
- Só com um token de API válido (`Bearer tf_...`): sem ele, a requisição segue normal (e o app
  responde 401), e uma resposta guardada não volta para um token revogado. As rotas de
  `/api/v1/auth/` (login, senhas) ficam de fora, e o `Set-Cookie` nunca é guardado: no banco não
  fica segredo de sessão.

Middleware ASGI, e não uma dependência: só ele vê a resposta inteira para guardá-la.
"""

import hashlib
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from chamados.core.errors import problem
from chamados.core.i18n import request_locale
from chamados.modules.identity.models import IdempotencyKey
from chamados.modules.identity.tokens import load_api_token

HEADER = "idempotency-key"
# Login, convite e senhas: respostas com cookie de sessão, nunca guardadas.
SKIP = "/api/v1/auth/"
MAX_LENGTH = 255
KEEP = timedelta(hours=24)
STALE = timedelta(minutes=5)


def digest(*parts: bytes) -> str:
    """SHA-256 das partes, separadas (a mesma conta no MCP, para o `request_id`)."""
    sha = hashlib.sha256()
    for part in parts:
        sha.update(part)
        sha.update(b"\x1f")
    return sha.hexdigest()


class IdempotencyMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        headers = Headers(scope=scope) if scope["type"] == "http" else None
        if (
            headers is None
            or scope["method"] != "POST"
            or not scope["path"].startswith("/api/")
            or scope["path"].startswith(SKIP)
            or (key := headers.get(HEADER)) is None
            or (authorization := headers.get("authorization")) is None
        ):
            await self.app(scope, receive, send)
            return
        sessionmaker = scope["app"].state.sessionmaker
        scheme, _, raw = authorization.partition(" ")
        async with sessionmaker() as db:
            valid = scheme.lower() == "bearer" and await load_api_token(db, raw.strip()) is not None
        if not valid:
            await self.app(scope, receive, send)
            return
        locale = request_locale(Request(scope))
        if not 0 < len(key) <= MAX_LENGTH:
            await problem(422, "Idempotency-Key: de 1 a 255 caracteres.", locale)(
                scope, receive, send
            )
            return

        body = await _read_body(receive)
        owner = digest(authorization.encode())
        fingerprint = digest(
            scope["method"].encode(), scope["path"].encode(), scope["query_string"], body
        )

        async with sessionmaker() as db:
            claimed = await db.scalar(
                insert(IdempotencyKey)
                .values(owner_hash=owner, key=key, fingerprint=fingerprint)
                .on_conflict_do_nothing()
                .returning(IdempotencyKey.id)
            )
            if claimed is None:
                # Uma primeira tentativa que parou no meio (o processo caiu) não trava a chave.
                claimed = await db.scalar(
                    update(IdempotencyKey)
                    .where(
                        IdempotencyKey.owner_hash == owner,
                        IdempotencyKey.key == key,
                        IdempotencyKey.fingerprint == fingerprint,
                        IdempotencyKey.status_code.is_(None),
                        IdempotencyKey.created_at < func.now() - STALE,
                    )
                    .values(created_at=func.now())
                    .returning(IdempotencyKey.id)
                )
            await db.commit()
            if claimed is None:
                saved = await db.scalar(
                    select(IdempotencyKey).where(
                        IdempotencyKey.owner_hash == owner, IdempotencyKey.key == key
                    )
                )
                await _answer_existing(saved, fingerprint, locale, scope, receive, send)
                return

        status = 500
        response_headers: list[list[str]] = []
        chunks: list[bytes] = []
        body_sent = False

        async def replay_receive() -> Message:
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        async def capture(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                response_headers.extend(
                    [k.decode("latin-1"), v.decode("latin-1")]
                    for k, v in message["headers"]
                    if k.lower() != b"set-cookie"
                )
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, replay_receive, capture)
        finally:
            async with sessionmaker() as db:
                if 200 <= status < 300:
                    await db.execute(
                        update(IdempotencyKey)
                        .where(IdempotencyKey.id == claimed)
                        .values(status_code=status, headers=response_headers, body=b"".join(chunks))
                    )
                else:
                    await db.execute(delete(IdempotencyKey).where(IdempotencyKey.id == claimed))
                await db.commit()


async def _read_body(receive: Receive) -> bytes:
    chunks: list[bytes] = []
    while True:
        message = await receive()
        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            return b"".join(chunks)


async def _answer_existing(
    saved: IdempotencyKey | None,
    fingerprint: str,
    locale: str,
    scope: Scope,
    receive: Receive,
    send: Send,
) -> None:
    # `saved` some se a primeira falhou entre as duas consultas: pode tentar de novo.
    if saved is None or saved.status_code is None:
        await problem(
            409, "Uma requisição com esta Idempotency-Key ainda está em andamento.", locale
        )(scope, receive, send)
    elif saved.fingerprint != fingerprint:
        await problem(422, "Esta Idempotency-Key já foi usada com outra requisição.", locale)(
            scope, receive, send
        )
    else:
        raw: list[Any] = [
            (k.encode("latin-1"), v.encode("latin-1")) for k, v in saved.headers or []
        ]
        raw.append((b"idempotent-replayed", b"true"))
        await send({"type": "http.response.start", "status": saved.status_code, "headers": raw})
        await send({"type": "http.response.body", "body": saved.body or b""})
