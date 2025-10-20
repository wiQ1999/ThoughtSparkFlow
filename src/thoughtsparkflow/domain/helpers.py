from __future__ import annotations

from typing import Optional


def normalize_plain_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def normalize_email(value: Optional[str]) -> Optional[str]:
    plain = normalize_plain_text(value)
    if plain is None:
        return None
    return plain.lower()


def normalize_category_name(value: Optional[str]) -> Optional[str]:
    plain = normalize_plain_text(value)
    if plain is None:
        return None
    return plain.casefold()

def safe_int(value: object) -> Optional[int]:
    try:
        integer = int(value)
    except (TypeError, ValueError):
        return None
    return integer if integer >= 0 else None


def ensure_positive_int(value: int | str, field: str) -> int:
    try:
        integer = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if integer <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return integer
