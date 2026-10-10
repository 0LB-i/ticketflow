"""Segredos aleatórios. No banco fica só o SHA-256 (docs/09 §9.4 e §9.7)."""

import hashlib
import secrets


def new_secret() -> tuple[str, str]:
    """(valor para o cliente, hash para o banco). 256 bits de entropia."""
    raw = secrets.token_urlsafe(32)
    return raw, sha256(raw)


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
