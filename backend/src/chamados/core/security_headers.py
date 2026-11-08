"""Cabeçalhos de segurança em todas as respostas (telas, API, /static, anexos e /mcp).

No app, e não no nginx: os do app chegam às instalações existentes com a atualização.
Middleware ASGI puro, e não o BaseHTTPMiddleware, que mexeria no envio das respostas em partes
(o FileResponse dos anexos) e no /mcp.
"""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

HEADERS = {
    # Nenhuma tela usa câmera, microfone, localização, pagamento ou USB.
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    # Uma janela aberta por outro site não fica com acesso a esta (window.opener).
    "Cross-Origin-Opener-Policy": "same-origin",
}


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in HEADERS.items():
                    headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)
