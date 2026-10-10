"""CPF, CNPJ, telefone e CEP: normalização e dígitos verificadores (sem banco).

O CNPJ alfanumérico (Receita Federal, a partir de julho de 2026) tem 12 caracteres de 0-9 ou A-Z
e 2 dígitos verificadores numéricos. O cálculo é o mesmo do numérico, com o valor de cada
caractere igual ao código ASCII menos 48; por isso a mesma função vale para os dois.
"""

import re

# fmt: off
UFS = frozenset({
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
    "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
})
# fmt: on


def only_digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def normalize_document(value: str) -> str:
    """Tira pontuação e espaços; letras ficam maiúsculas (CNPJ alfanumérico)."""
    return re.sub(r"[^0-9A-Z]", "", value.upper())


def _check_digit(chars: str, weights: list[int]) -> int:
    total = sum((ord(c) - 48) * w for c, w in zip(chars, weights, strict=True))
    rest = total % 11
    return 0 if rest < 2 else 11 - rest


def valid_cpf(cpf: str) -> bool:
    if not re.fullmatch(r"\d{11}", cpf) or len(set(cpf)) == 1:
        return False
    first = _check_digit(cpf[:9], list(range(10, 1, -1)))
    second = _check_digit(cpf[:10], list(range(11, 1, -1)))
    return cpf[9:] == f"{first}{second}"


def valid_cnpj(cnpj: str) -> bool:
    if not re.fullmatch(r"[0-9A-Z]{12}\d{2}", cnpj) or len(set(cnpj)) == 1:
        return False
    weights = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    first = _check_digit(cnpj[:12], weights[1:])
    second = _check_digit(cnpj[:13], weights)
    return cnpj[12:] == f"{first}{second}"


def normalize_phone(value: str) -> str:
    """Só os dígitos, com o DDD e sem o +55."""
    digits = only_digits(value)
    if len(digits) in (12, 13) and digits.startswith("55"):
        digits = digits[2:]
    return digits


def valid_phone(digits: str) -> bool:
    return bool(re.fullmatch(r"[1-9]{2}\d{8,9}", digits))
