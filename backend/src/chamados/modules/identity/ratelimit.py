"""Proteção contra força bruta no login (docs/09 §9.3).

- Por IP: no máximo 20 falhas em 15 minutos (em memória: a API roda num único processo,
  ADR 0010). Acima disso, 429.
- Por conta: a partir de 5 falhas seguidas, tentativas antes do intervalo de espera
  (2, 4, 8… segundos, até 60) são recusadas sem conferir a senha; com 10 falhas a conta
  fica bloqueada por 15 minutos e o dono recebe um e-mail.
"""

import time
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime, timedelta

IP_MAX_FAILURES = 20
IP_WINDOW_SECONDS = 15 * 60
DELAY_AFTER = 5
LOCK_AFTER = 10
LOCK_FOR = timedelta(minutes=15)


class IpLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        # IP → horas das falhas na janela. Um IP sem falha na janela sai do dicionário.
        self._failures: dict[str, deque[float]] = {}
        self._swept = clock()

    def _sweep(self, t: float) -> None:
        """Uma vez por janela, esquece os IPs que não falharam nela: sem isso, cada IP que já
        tentou entrar ficaria na memória até o serviço reiniciar."""
        if t - self._swept < IP_WINDOW_SECONDS:
            return
        self._swept = t
        for ip in [
            ip for ip, q in self._failures.items() if not q or q[-1] <= t - IP_WINDOW_SECONDS
        ]:
            del self._failures[ip]

    def blocked(self, ip: str) -> int:
        """Segundos até poder tentar de novo (0 = liberado)."""
        t = self._clock()
        self._sweep(t)
        q = self._failures.get(ip)
        if q is None:
            return 0
        while q and q[0] <= t - IP_WINDOW_SECONDS:
            q.popleft()
        if not q:
            del self._failures[ip]
            return 0
        if len(q) < IP_MAX_FAILURES:
            return 0
        return int(q[0] + IP_WINDOW_SECONDS - t) + 1

    def begin(self, ip: str) -> float:
        """Conta a tentativa como falha desde já e devolve a marca dela, que `succeeded` retira.
        Chamada logo depois de `blocked`, sem `await` no meio: tentativas simultâneas não passam
        todas pela conferência antes de a primeira falhar."""
        stamp = self._clock()
        self._failures.setdefault(ip, deque()).append(stamp)
        return stamp

    def succeeded(self, ip: str, stamp: float) -> None:
        """O login deu certo: a tentativa sai da contagem."""
        q = self._failures.get(ip)
        if q is None:
            return
        with suppress(ValueError):  # já saiu da janela
            q.remove(stamp)
        if not q:
            del self._failures[ip]


def account_must_wait(failed: int, last_failed_at: datetime | None, at: datetime) -> bool:
    if failed < DELAY_AFTER or last_failed_at is None:
        return False
    wait = min(2 ** (failed - DELAY_AFTER + 1), 60)
    return at < last_failed_at + timedelta(seconds=wait)
