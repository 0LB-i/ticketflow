"""Vínculo dos envios aos chamados e limpeza dos que sobraram (docs/11 §11.4)."""

import uuid
from datetime import timedelta
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from chamados.modules.attachments import storage
from chamados.modules.attachments.files import MAX_PER_TICKET
from chamados.modules.attachments.models import Attachment
from chamados.modules.identity.deps import Auth
from chamados.modules.tickets.models import Ticket, TicketComment
from chamados.modules.tickets.schemas import AttachmentOut, UserRef

ORPHAN_TTL = timedelta(hours=24)


async def link(
    db: AsyncSession,
    auth: Auth,
    ticket: Ticket,
    ids: list[uuid.UUID],
    comment: TicketComment | None = None,
) -> None:
    """Vincula envios ao chamado (e ao comentário). Só quem enviou, e uma vez só.

    Os que já estão neste mesmo lugar são ignorados: ao editar um comentário, a interface
    manda de novo as imagens que ele já tinha.
    """
    if not ids:
        return
    rows = (await db.scalars(select(Attachment).where(Attachment.public_id.in_(ids)))).all()
    comment_id = comment.id if comment else None
    new = [a for a in rows if (a.ticket_id, a.comment_id) != (ticket.id, comment_id)]
    if len(rows) != len(set(ids)) or any(
        a.linked_at is not None or a.uploaded_by != auth.user.id for a in new
    ):
        raise HTTPException(422, "Anexo não encontrado ou já usado.")
    if not new:
        return
    used = await db.scalar(
        select(func.coalesce(func.sum(Attachment.size_bytes), 0)).where(
            Attachment.ticket_id == ticket.id
        )
    )
    if (used or 0) + sum(a.size_bytes for a in new) > MAX_PER_TICKET:
        raise HTTPException(422, "Os anexos deste chamado passariam do limite de 200 MB.")
    for a in new:
        a.ticket_id = ticket.id
        a.comment_id = comment_id
        a.linked_at = func.now()


async def of_ticket(db: AsyncSession, ticket_id: int) -> list[AttachmentOut]:
    rows = await db.execute(
        select(Attachment, TicketComment.public_id)
        .outerjoin(TicketComment, TicketComment.id == Attachment.comment_id)
        # Os anexos de uma tarefa removida saem junto com ela.
        .where(Attachment.ticket_id == ticket_id, TicketComment.deleted_at.is_(None))
        .order_by(Attachment.created_at, Attachment.id)
    )
    return [out(a, comment_public_id) for a, comment_public_id in rows]


def out(a: Attachment, comment_public_id: uuid.UUID | None = None) -> AttachmentOut:
    return AttachmentOut(
        id=a.public_id,
        filename=a.filename,
        content_type=a.content_type,
        size_bytes=a.size_bytes,
        comment_id=comment_public_id,
        uploaded_by=UserRef(id=a.uploader.public_id, display_name=a.uploader.display_name),
        created_at=a.created_at,
    )


async def purge(db: AsyncSession, root: Path) -> int:
    """Apaga os envios não vinculados há mais de 24 h (banco e disco). Devolve quantos."""
    rows = (
        await db.scalars(
            select(Attachment).where(
                Attachment.linked_at.is_(None),
                Attachment.created_at < func.now() - ORPHAN_TTL,
            )
        )
    ).all()
    for a in rows:
        await db.delete(a)
    await db.commit()
    for a in rows:
        storage.delete(root, a.storage_key)
    return len(rows)
