"""Core package for thoughtsparkflow."""

try:
    from importlib.metadata import version  # Python 3.8+
    __version__ = version("thoughtsparkflow")
except Exception:
    __version__ = "0.0.0"