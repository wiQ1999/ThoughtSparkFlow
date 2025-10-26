"""Core package for thoughtsparkflow."""

from .application.use_cases.generate_drafts_process import GenerateDraftsProcess

try:
    from importlib.metadata import version  # Python 3.8+
    __version__ = version("thoughtsparkflow")
except Exception:
    __version__ = "0.0.0"

__all__ = ["GenerateDraftsProcess", "__version__"]
