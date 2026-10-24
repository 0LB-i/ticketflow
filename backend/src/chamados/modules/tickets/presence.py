"""Quem está com o chamado aberto (docs/10 §10.6, "Colisão").

No banco (`ticket_presence`, UNLOGGED), e não na memória: com vários workers da API, cada um
veria só quem caiu nele.
"""

import uuid
from datetime import timedelta

from sqlalchemy import delete, func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from chamados.modules.identity.models import User
from chamados.modules.tickets.models import TicketPresence

TTL_SECONDS = 45  # a tela pergunta a cada 20 s; quem passa disso fechou o chamado ou escondeu a aba


async def touch(db: AsyncSession, ticket_id: uuid.UUID, user_id: int) -> list[str]:
    """Registra que a pessoa está com o chamado aberto e devolve quem mais está (por nome).

    Quem passou do prazo sai antes, de todos os chamados: sem isso, a tabela só cresceria. As
    linhas que outra requisição está apagando ou renovando ficam para ela (SKIP LOCKED), sem
    esperar uma pela outra."""
    expired = TicketPresence.seen_at <= func.now() - timedelta(seconds=TTL_SECONDS)
    key = tuple_(TicketPresence.ticket_id, TicketPresence.user_id)
    await db.execute(
        delete(TicketPresence).where(
            key.in_(
                select(TicketPresence.ticket_id, TicketPresence.user_id)
                .where(expired)
                .with_for_update(skip_locked=True)
            )
        )
    )
    await db.execute(
        insert(TicketPresence)
        .values(ticket_id=ticket_id, user_id=user_id)
        .on_conflict_do_update(
            index_elements=[TicketPresence.ticket_id, TicketPresence.user_id],
            set_={"seen_at": func.now()},
        )
    )
    names = await db.scalars(
        select(User.display_name)
        .join(TicketPresence, TicketPresence.user_id == User.id)
        .where(TicketPresence.ticket_id == ticket_id, User.id != user_id, ~expired)
    )
    result = sorted(names)
    await db.commit()
    return result
