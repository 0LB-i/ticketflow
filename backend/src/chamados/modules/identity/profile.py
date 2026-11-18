"""Foto do perfil (tela Meu perfil). A imagem enviada vira um WebP 256×256, recortado no centro:
a foto do celular serve sem a pessoa diminuir antes, e os metadados (local, câmera) não ficam.
"""

import hashlib
import io

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chamados.modules.identity.models import User

AVATAR_MAX_BYTES = 5 * 1024 * 1024
AVATAR_SIZE = 256
# Abrir a imagem só lê o cabeçalho; acima disso ela nem é decodificada (bomba de descompressão).
MAX_PIXELS = 40_000_000
INVALID_AVATAR = "Foto inválida: envie uma imagem PNG, JPEG ou WebP."


def _webp(raw: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(raw), formats=("PNG", "JPEG", "WEBP")) as image:
            if image.width * image.height > MAX_PIXELS:
                raise HTTPException(422, INVALID_AVATAR)
            square = ImageOps.fit(
                ImageOps.exif_transpose(image).convert("RGBA"), (AVATAR_SIZE, AVATAR_SIZE)
            )
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, INVALID_AVATAR) from exc
    out = io.BytesIO()
    square.save(out, "WEBP", quality=85)
    return out.getvalue()


async def set_avatar(db: AsyncSession, user: User, raw: bytes) -> None:
    if len(raw) > AVATAR_MAX_BYTES:
        raise HTTPException(422, "A foto pode ter no máximo 5 MB.")
    data = await run_in_threadpool(_webp, raw)
    user.avatar = data
    user.avatar_hash = hashlib.sha256(data).hexdigest()[:16]
    await db.commit()


async def remove_avatar(db: AsyncSession, user: User) -> None:
    user.avatar = None
    user.avatar_hash = None
    await db.commit()


async def avatar(db: AsyncSession, user: User) -> bytes | None:
    return await db.scalar(select(User.avatar).where(User.id == user.id))
