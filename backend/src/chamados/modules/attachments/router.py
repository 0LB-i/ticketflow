"""Envio (1ª etapa) e download dos anexos (docs/11 §11.4 e §11.7)."""

import uuid

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from chamados.core.permissions import P, can
from chamados.db.session import DB
from chamados.modules.attachments import service, storage
from chamados.modules.attachments.files import HEAD_BYTES, MAX_BYTES, clean_filename, file_type
from chamados.modules.attachments.models import Attachment
from chamados.modules.audit.service import record
from chamados.modules.identity.deps import CurrentAuth
from chamados.modules.tickets import service as tickets
from chamados.modules.tickets.models import Ticket
from chamados.modules.tickets.schemas import AttachmentOut

router = APIRouter(tags=["anexos"])
NOT_FOUND = "Anexo não encontrado."


@router.post("/uploads", response_model=AttachmentOut, status_code=201)
async def upload(file: UploadFile, auth: CurrentAuth, request: Request, db: DB) -> AttachmentOut:
    """Guarda o arquivo até ele ser vinculado a um chamado ou comentário (`attachment_ids`)."""
    if not (can(auth.actor, P.TICKET_COMMENT) or can(auth.actor, P.TICKET_CREATE)):
        raise HTTPException(403, "Você não tem permissão para esta ação.")
    filename = clean_filename(file.filename)
    ftype = file_type(filename)
    if ftype is None:
        raise HTTPException(422, "Tipo de arquivo não permitido.")
    if not file.size:
        raise HTTPException(422, "O arquivo está vazio.")
    if file.size > MAX_BYTES:
        raise HTTPException(413, "O arquivo passa do limite de 25 MB.")
    head = await file.read(HEAD_BYTES)
    await file.seek(0)
    if not ftype.matches(head):
        raise HTTPException(422, "O conteúdo do arquivo não corresponde à extensão.")

    root = request.app.state.settings.files_dir
    key = storage.new_key()
    size, sha256 = await run_in_threadpool(storage.save, root, key, file.file)
    attachment = Attachment(
        filename=filename,
        content_type=ftype.content_type,
        size_bytes=size,
        sha256=sha256,
        storage_key=key,
        uploaded_by=auth.user.id,
    )
    db.add(attachment)
    try:
        await db.commit()
    except Exception:
        storage.delete(root, key)
        raise
    await db.refresh(attachment)
    return service.out(attachment)


@router.get(
    "/attachments/{attachment_id}",
    response_class=FileResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def download(
    attachment_id: uuid.UUID, auth: CurrentAuth, request: Request, db: DB
) -> FileResponse:
    """Quem vê o chamado baixa; um envio ainda não vinculado, só quem o enviou."""
    attachment = await db.scalar(select(Attachment).where(Attachment.public_id == attachment_id))
    if attachment is None:
        raise HTTPException(404, NOT_FOUND)
    if attachment.ticket_id is None:
        if attachment.uploaded_by != auth.user.id:
            raise HTTPException(404, NOT_FOUND)
    else:
        ticket_ref = await db.scalar(
            select(Ticket.public_id).where(Ticket.id == attachment.ticket_id)
        )
        ticket = await tickets.load(db, auth, str(ticket_ref))  # 403 para quem não vê
        if ticket.category and ticket.category.is_confidential:
            record(
                db,
                "attachment.confidential_downloaded",
                request=request,
                actor_user_id=auth.user.id,
                target_type="attachment",
                target_id=attachment.public_id,
            )
            await db.commit()

    path = storage.path(request.app.state.settings.files_dir, attachment.storage_key)
    if not path.is_file():
        raise HTTPException(404, NOT_FOUND)
    ftype = file_type(attachment.filename)
    return FileResponse(
        path,
        media_type=attachment.content_type,
        filename=attachment.filename,
        content_disposition_type="inline" if ftype and ftype.inline else "attachment",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
            "Cache-Control": "private, max-age=86400",
        },
    )
