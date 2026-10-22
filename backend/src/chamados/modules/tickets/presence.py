"""Quem está com o chamado aberto (docs/10 §10.6, "Colisão").

Em memória, no processo da API, como o limite de tentativas de login (identity/ratelimit.py): é
um dado passageiro, e a API roda num processo só. Com mais de um processo, isto iria para o banco.
"""

import time
import uuid
from collections.abc import Callable

TTL_SECONDS = 45  # a tela pergunta a cada 20 s; quem passa disso fechou o chamado


class Presence:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        # chamado (public_id) → pessoa (id) → (nome, hora)
        self._seen: dict[uuid.UUID, dict[int, tuple[str, float]]] = {}

    def touch(self, ticket_id: uuid.UUID, user_id: int, name: str) -> list[str]:
        """Registra que a pessoa está com o chamado aberto e devolve quem mais está (por nome)."""
        now = self._clock()
        seen = self._seen.setdefault(ticket_id, {})
        for uid in [u for u, (_, at) in seen.items() if now - at > TTL_SECONDS]:
            del seen[uid]
        seen[user_id] = (name, now)
        return sorted(n for uid, (n, _) in seen.items() if uid != user_id)
