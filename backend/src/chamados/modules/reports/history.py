"""O Histórico e a cascata da aba Clientes (docs/14 §14.7): os PDFs baixados com um cliente só,
de cada pessoa. Só a própria pessoa vê os seus; a cascata tira da lista de clientes dela os que já
tiveram relatório no dia (no fuso da máquina)."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chamados.core.timezone import LOCAL_TZ
from chamados.modules.clients.models import Client, label_of
from chamados.modules.reports.models import ReportExport

Kind = Literal["simple", "detailed"]  # o PDF simplificado ou o detalhado
LISTED = 200  # as entradas mais recentes no Histórico


def record(
    db: AsyncSession,
    user_id: int,
    client_id: int,
    kind: Kind,
    start: date,
    end: date,
    query: dict[str, Any],
) -> None:
    """Um PDF gerado; `query`, os parâmetros para gerar de novo (quem chama faz o commit)."""
    db.add(
        ReportExport(
            user_id=user_id,
            client_id=client_id,
            kind=kind,
            start_date=start,
            end_date=end,
            query=query,
        )
    )


async def clients_today(db: AsyncSession, user_id: int) -> list[uuid.UUID]:
    """Os clientes com relatório da pessoa hoje: a cascata os tira da lista."""
    midnight = datetime.combine(datetime.now(LOCAL_TZ).date(), time(), LOCAL_TZ)
    found = await db.scalars(
        select(Client.public_id)
        .join(ReportExport, ReportExport.client_id == Client.id)
        .where(ReportExport.user_id == user_id, ReportExport.created_at >= midnight)
        .distinct()
    )
    return list(found)


@dataclass
class Entry:
    created_at: datetime
    client: str
    start: date
    end: date
    kind: Kind
    query: dict[str, Any]


async def entries(db: AsyncSession, user_id: int) -> list[Entry]:
    """O Histórico da pessoa, do mais recente para o mais antigo (os LISTED primeiros)."""
    rows = await db.execute(
        select(
            ReportExport.created_at,
            Client.name,
            Client.trade_name,
            Client.city,
            Client.state,
            ReportExport.start_date,
            ReportExport.end_date,
            ReportExport.kind,
            ReportExport.query,
        )
        .join(Client, Client.id == ReportExport.client_id)
        .where(ReportExport.user_id == user_id)
        .order_by(ReportExport.created_at.desc(), ReportExport.id.desc())
        .limit(LISTED)
    )
    return [
        Entry(at, label_of(name, trade_name, city, state), start, end, kind, query)
        for at, name, trade_name, city, state, start, end, kind, query in rows
    ]
