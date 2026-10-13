"""Armazenamento local dos anexos (docs/11 §11.6), em FILES_DIR.

Os arquivos ficam em `attachments/AAAA/MM/<uuid>`, sem o nome original. A gravação passa por
um arquivo temporário na mesma pasta e só então ganha o nome final.
"""

import hashlib
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

CHUNK = 1024 * 1024


def new_key() -> str:
    now = datetime.now(UTC)
    return f"attachments/{now:%Y}/{now:%m}/{uuid.uuid4().hex}"


def path(root: Path, key: str) -> Path:
    return root / key


def save(root: Path, key: str, source: BinaryIO) -> tuple[int, str]:
    """Copia o arquivo e devolve o tamanho e o SHA-256. Roda fora do loop (é bloqueante)."""
    target = path(root, key)
    target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.tmp")
    digest = hashlib.sha256()
    size = 0
    with temp.open("wb") as out:
        while chunk := source.read(CHUNK):
            digest.update(chunk)
            size += len(chunk)
            out.write(chunk)
    temp.chmod(0o640)
    os.replace(temp, target)
    return size, digest.hexdigest()


def delete(root: Path, key: str) -> None:
    path(root, key).unlink(missing_ok=True)
