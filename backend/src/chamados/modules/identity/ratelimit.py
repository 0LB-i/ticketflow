"""Proteção contra força bruta no login (docs/09 §9.3).

- Por IP: no máximo 20 falhas em 15 minutos (no banco, `login_ip_failures`: vale para todos
  os workers da API). Acima disso, 429.
- Por conta: a partir de 5 falhas seguidas, tentativas antes do intervalo de espera
  (2, 4, 8… segundos, até 60) são recusadas sem conferir a senha; com 10 falhas a conta
  fica bloqueada por 15 minutos e o dono recebe um e-mail.
"""

from datetime import datetime, timedelta

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from chamados.modules.identity.models import LoginIpFailure

IP_MAX_FAILURES = 20
IP_WINDOW_SECONDS = 15 * 60
DELAY_AFTER = 5
LOCK_AFTER = 10
LOCK_FOR = timedelta(minutes=15)


async def ip_attempt(db: AsyncSession, ip: str) -> tuple[int, int | None]:
    """Confere o limite do IP e, se ele está liberado, já conta a tentativa como falha, que
    `ip_succeeded` retira. Devolve os segundos até poder tentar de novo (0 = liberado) e a marca
    da tentativa (None se recusada).

    Numa transação curta, com uma trava por IP: tentativas simultâneas, mesmo em workers
    diferentes, esperam a anterior contar antes de conferir. A trava sai no commit, antes da
    conferência da senha: logins do mesmo IP (um escritório inteiro) não esperam o Argon2 uns
    dos outros."""
    window = timedelta(seconds=IP_WINDOW_SECONDS)
    since = func.now() - window
    await db.execute(select(func.pg_advisory_xact_lock(func.hashtext(ip))))
    # As tentativas que saíram da janela, de todos os IPs: sem isso, a tabela só cresceria. As
    # que outra requisição está apagando ficam para ela (SKIP LOCKED).
    await db.execute(
        delete(LoginIpFailure).where(
            LoginIpFailure.id.in_(
                select(LoginIpFailure.id)
                .where(LoginIpFailure.at <= since)
                .with_for_update(skip_locked=True)
            )
        )
    )
    # Quantas falhas na janela e em quantos segundos a mais antiga sai dela.
    failures, seconds = (
        await db.execute(
            select(
                func.count(),
                func.extract("epoch", func.min(LoginIpFailure.at) + window - func.now()),
            ).where(LoginIpFailure.ip == ip, LoginIpFailure.at > since)
        )
    ).one()
    if failures >= IP_MAX_FAILURES:
        await db.commit()
        return int(seconds) + 1, None
    attempt = await db.scalar(insert(LoginIpFailure).values(ip=ip).returning(LoginIpFailure.id))
    await db.commit()
    return 0, attempt


async def ip_succeeded(db: AsyncSession, attempt: int) -> None:
    """O login deu certo: a tentativa sai da contagem (no commit de quem chama)."""
    await db.execute(delete(LoginIpFailure).where(LoginIpFailure.id == attempt))


def account_must_wait(failed: int, last_failed_at: datetime | None, at: datetime) -> bool:
    if failed < DELAY_AFTER or last_failed_at is None:
        return False
    wait = min(2 ** (failed - DELAY_AFTER + 1), 60)
    return at < last_failed_at + timedelta(seconds=wait)
