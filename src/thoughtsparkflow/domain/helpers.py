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

def safe_int(value: Optional[int | str]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

def safe_id(value: Optional[int | str]) -> Optional[int]:
    if value is None:
        return None
    try:
        integer = int(value)
    except (TypeError, ValueError):
        return None
    return integer if integer >= 0 else None


def ensure_positive_int(value: Optional[int | str], field: str) -> int:
    if value is None:
        raise ValueError(f"{field} must not be None.")
    try:
        integer = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if integer <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return integer


def ensure_non_empty_text(value: Optional[str], field: str) -> str:
    plain = normalize_plain_text(value)
    if plain is None:
        raise ValueError(f"{field} must not be empty.")
    return plain
