from __future__ import annotations
from collections import Counter
from typing import Callable, Iterable, List

from .schemas import FileConfig

class ConfigValidationError(Exception):
    """A summary of the configuration validation error.

    Args:
        Exception (Exception): The original exception.
    """

def check_authors_non_empty(cfg: FileConfig) -> List[str]:
    """Checks whether authors list is non-empty.

    Args:
        cfg (FileConfig): The configuration object to check.

    Returns:
        List[str]: A list of error messages, if any.
    """
    return [] if cfg.authors else ["authors: must contain at least one author"]

def check_unique_author_emails(cfg: FileConfig) -> List[str]:
    """Checks for unique email addresses among authors in configuration.

    Args:
        cfg (FileConfig): The configuration object to check.

    Returns:
        List[str]: A list of error messages, if any.
    """
    emails = [str(a.email) for a in cfg.authors]
    dupes = [e for e, cnt in Counter(emails).items() if cnt > 1]
    return [f"authors: duplicate emails -> {', '.join(dupes)}"] if dupes else []

Validator = Callable[[FileConfig], List[str]]

def run_validations(cfg: FileConfig, checks: Iterable[Validator]) -> None:
    """Runs the specified validation checks on the configuration.

    Args:
        cfg (FileConfig): The configuration object to validate.
        checks (Iterable[Validator]): The validation checks to run.

    Raises:
        ConfigValidationError: If any validation errors are found.
    """
    errors: List[str] = []
    for check in checks:
        errors.extend(check(cfg))
    if errors:
        bullet = "\n  - " + "\n  - ".join(errors)
        raise ConfigValidationError("Configuration validation failed:" + bullet)
