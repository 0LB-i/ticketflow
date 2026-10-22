"""Texto que chega dos formulários: sem espaços nas pontas, e vazio vira nulo ou erro; e o padrão
das buscas por "contém"."""

from fastapi import HTTPException


def optional_text(value: str | None) -> str | None:
    return (value or "").strip() or None


def required_text(value: str | None, message: str) -> str:
    text = optional_text(value)
    if text is None:
        raise HTTPException(422, message)
    return text


LIKE_ESCAPE = "\\"


def contains_pattern(value: str) -> str:
    """Padrão do (I)LIKE para "contém o texto". `%` e `_` digitados valem como eles mesmos, não
    como curingas: use com `escape=LIKE_ESCAPE`."""
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
