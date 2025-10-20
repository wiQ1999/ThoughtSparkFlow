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
