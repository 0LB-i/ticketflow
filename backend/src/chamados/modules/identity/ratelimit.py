"""Proteção contra força bruta no login (docs/09 §9.3).

- Por IP: no máximo 20 falhas em 15 minutos (em memória: a API roda num único processo,
  ADR 0010). Acima disso, 429.
- Por conta: a partir de 5 falhas seguidas, tentativas antes do intervalo de espera
  (2, 4, 8… segundos, até 60) são recusadas sem conferir a senha; com 10 falhas a conta
  fica bloqueada por 15 minutos e o dono recebe um e-mail.
"""

import time
from collections import defaultdict, deque
from datetime import datetime, timedelta

IP_MAX_FAILURES = 20
IP_WINDOW_SECONDS = 15 * 60
DELAY_AFTER = 5
LOCK_AFTER = 10
LOCK_FOR = timedelta(minutes=15)


class IpLimiter:
    def __init__(self) -> None:
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, ip: str, t: float) -> deque[float]:
        q = self._failures[ip]
        while q and q[0] <= t - IP_WINDOW_SECONDS:
            q.popleft()
        return q

    def blocked(self, ip: str) -> int:
        """Segundos até poder tentar de novo (0 = liberado)."""
        t = time.monotonic()
        q = self._prune(ip, t)
        if len(q) < IP_MAX_FAILURES:
            return 0
        return int(q[0] + IP_WINDOW_SECONDS - t) + 1

    def fail(self, ip: str) -> None:
        self._failures[ip].append(time.monotonic())


def account_must_wait(failed: int, last_failed_at: datetime | None, at: datetime) -> bool:
    if failed < DELAY_AFTER or last_failed_at is None:
        return False
    wait = min(2 ** (failed - DELAY_AFTER + 1), 60)
    return at < last_failed_at + timedelta(seconds=wait)
