"""Texto que chega dos formulários: sem espaços nas pontas, e vazio vira nulo ou erro."""

from fastapi import HTTPException


def optional_text(value: str | None) -> str | None:
    return (value or "").strip() or None


def required_text(value: str | None, message: str) -> str:
    text = optional_text(value)
    if text is None:
        raise HTTPException(422, message)
    return text
