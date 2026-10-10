"""Senhas: Argon2id e regras do NIST SP 800-63B (docs/09 §9.3)."""

from functools import lru_cache
from importlib.resources import files

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MIN_LENGTH = 8
MAX_LENGTH = 256

_hasher = PasswordHasher()
# Hash de referência para gastar o mesmo tempo quando o e-mail não existe.
_DUMMY = _hasher.hash("senha-de-referencia-para-tempo-constante")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> tuple[bool, bool]:
    """(senha confere?, hash precisa ser refeito com os parâmetros atuais?)"""
    try:
        _hasher.verify(password_hash or _DUMMY, password)
    except (VerificationError, InvalidHashError):
        return False, False
    if password_hash is None:
        return False, False
    return True, _hasher.check_needs_rehash(password_hash)


@lru_cache
def _common() -> frozenset[str]:
    text = files("chamados.modules.identity").joinpath("senhas_comuns.txt").read_text("utf-8")
    return frozenset(
        line.strip().lower() for line in text.splitlines() if line.strip() and line[0] != "#"
    )


def password_problem(password: str, *identifiers: str | None) -> str | None:
    """Motivo para recusar a senha nova, ou None se ela serve. `identifiers`: e-mail, usuário."""
    if len(password) < MIN_LENGTH:
        return f"A senha precisa ter pelo menos {MIN_LENGTH} caracteres."
    if len(password) > MAX_LENGTH:
        return f"A senha pode ter no máximo {MAX_LENGTH} caracteres."
    lowered = password.lower()
    own = {part.lower() for i in identifiers if i for part in (i, i.split("@")[0])}
    if lowered in _common() or lowered in own:
        return "Essa senha é muito comum ou fácil de adivinhar. Escolha outra."
    if len(set(password)) < 4:
        return "Essa senha é muito comum ou fácil de adivinhar. Escolha outra."
    return None
