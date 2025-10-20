from __future__ import annotations


class ProcessAbort(Exception):
    """Raised when the business process must be aborted."""


__all__ = ["ProcessAbort"]
