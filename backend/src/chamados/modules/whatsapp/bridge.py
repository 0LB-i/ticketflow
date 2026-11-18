"""Cliente da ponte do WhatsApp (whatsapp-bridge/bridge.js), pelo socket Unix `bridge.sock`.

A ponte é um processo à parte (ticketflow-whatsapp.service), com a Baileys. Sem porta e sem senha:
o socket fica na pasta da ponte, que só o usuário do serviço abre.
"""

import uuid
from pathlib import Path
from typing import Any

import httpx2

from chamados.config import Settings

DOWN = "A ponte do WhatsApp não está rodando."
DISCONNECTED = "O número está desconectado do WhatsApp."
REFUSED = "A ponte do WhatsApp recusou o pedido."


class BridgeError(Exception):
    """A ponte não respondeu ou recusou o pedido (a mensagem vai para a tela)."""


class Bridge:
    def __init__(self, socket: Path) -> None:
        self.socket = socket

    async def _request(self, method: str, path: str, *, seconds: float = 15, **kwargs: Any) -> Any:
        transport = httpx2.AsyncHTTPTransport(uds=str(self.socket))
        try:
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://ponte", timeout=seconds
            ) as client:
                response = await client.request(method, path, **kwargs)
        except httpx2.TransportError as e:
            raise BridgeError(DOWN) from e
        if response.status_code == 503:
            raise BridgeError(DISCONNECTED)
        if response.status_code != 200:
            raise BridgeError(REFUSED)
        return response.json()

    async def channels(self) -> dict[uuid.UUID, dict[str, Any]]:
        """O estado de cada número na ponte (e o QR code em SVG, durante o pareamento)."""
        return {uuid.UUID(c["id"]): c for c in await self._request("GET", "/channels")}

    async def start(self, channel: uuid.UUID) -> dict[str, Any]:
        result: dict[str, Any] = await self._request("POST", f"/channels/{channel}/start")
        return result

    async def logout(self, channel: uuid.UUID) -> None:
        await self._request("POST", f"/channels/{channel}/logout")

    async def send_text(self, channel: uuid.UUID, jid: str, text: str, wa_id: str) -> None:
        await self._request(
            "POST", f"/channels/{channel}/send", json={"jid": jid, "text": text, "id": wa_id}
        )

    async def events(self, wait: int) -> list[dict[str, Any]]:
        """Os eventos ainda não confirmados; sem nenhum, espera até `wait` segundos."""
        events: list[dict[str, Any]] = await self._request(
            "GET", "/events", params={"after": 0, "wait": wait}, seconds=wait + 10
        )
        return events

    async def ack(self, upto: int) -> None:
        await self._request("POST", "/events/ack", json={"upto": upto})


def get_bridge(settings: Settings) -> Bridge:
    return Bridge(settings.whatsapp_dir / "bridge.sock")
