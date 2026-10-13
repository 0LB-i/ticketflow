"""Tipos de arquivo aceitos (docs/11 §11.2): a extensão e o conteúdo real precisam bater.

Só passa o que está na lista; executáveis, scripts e conteúdo web ativo (html, svg) nunca
entram. Compactados e Office com macro também ficam de fora (bloqueados por padrão).
"""

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

MAX_BYTES = 25 * 1024 * 1024  # por arquivo (docs/11 §11.3)
MAX_PER_TICKET = 200 * 1024 * 1024
HEAD_BYTES = 8192  # o que se lê do começo do arquivo para conferir o conteúdo

OOXML = "application/vnd.openxmlformats-officedocument."
ODF = "application/vnd.oasis.opendocument."


def _starts(*signatures: bytes) -> Callable[[bytes], bool]:
    return lambda head: head.startswith(signatures)


def _webp(head: bytes) -> bool:
    return head[:4] == b"RIFF" and head[8:12] == b"WEBP"


def _heic(head: bytes) -> bool:
    return head[4:8] == b"ftyp" and head[8:12] in (b"heic", b"heix", b"mif1", b"msf1", b"hevc")


def _text(head: bytes) -> bool:
    """Texto: sem bytes nulos (um binário renomeado para .txt quase sempre tem)."""
    return b"\x00" not in head


_zip = _starts(b"PK\x03\x04")


@dataclass(frozen=True)
class FileType:
    content_type: str
    matches: Callable[[bytes], bool]
    inline: bool = False  # o navegador pode mostrar (imagens e PDF); o resto é baixado


TYPES: dict[str, FileType] = {
    "png": FileType("image/png", _starts(b"\x89PNG\r\n\x1a\n"), inline=True),
    "jpg": FileType("image/jpeg", _starts(b"\xff\xd8\xff"), inline=True),
    "jpeg": FileType("image/jpeg", _starts(b"\xff\xd8\xff"), inline=True),
    "gif": FileType("image/gif", _starts(b"GIF87a", b"GIF89a"), inline=True),
    "webp": FileType("image/webp", _webp, inline=True),
    "heic": FileType("image/heic", _heic),
    "pdf": FileType("application/pdf", _starts(b"%PDF-"), inline=True),
    "docx": FileType(OOXML + "wordprocessingml.document", _zip),
    "xlsx": FileType(OOXML + "spreadsheetml.sheet", _zip),
    "pptx": FileType(OOXML + "presentationml.presentation", _zip),
    "odt": FileType(ODF + "text", _zip),
    "ods": FileType(ODF + "spreadsheet", _zip),
    "odp": FileType(ODF + "presentation", _zip),
    "msg": FileType("application/vnd.ms-outlook", _starts(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")),
    "rtf": FileType("application/rtf", _starts(b"{\\rtf")),
    "eml": FileType("message/rfc822", _text),
    "txt": FileType("text/plain", _text),
    "log": FileType("text/plain", _text),
    "csv": FileType("text/csv", _text),
    "md": FileType("text/markdown", _text),
    "json": FileType("application/json", _text),
    "xml": FileType("application/xml", _text),
    "yaml": FileType("application/yaml", _text),
    "yml": FileType("application/yaml", _text),
}


def extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def file_type(filename: str) -> FileType | None:
    return TYPES.get(extension(filename))


def clean_filename(raw: str | None) -> str:
    """Sem caminho nem caracteres de controle, até 255 caracteres (mantendo a extensão)."""
    name = unicodedata.normalize("NFC", raw or "")
    name = re.split(r"[\\/]", name)[-1]
    name = "".join(c for c in name if unicodedata.category(c)[0] != "C").strip(" .")
    if len(name) > 255:
        ext = extension(name)
        stem = name[: 255 - len(ext) - 1].rstrip() if ext else name[:255]
        name = f"{stem}.{ext}" if ext else stem
    return name
