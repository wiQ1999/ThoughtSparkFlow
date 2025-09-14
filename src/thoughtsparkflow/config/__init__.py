"""Configuration subpackage for thoughtsparkflow."""

from .schemas import Author, FileConfig
from .env_settings import EnvSettings
from .loader import (
    AppConfig,
    load_config,
    load_file_config,
    load_env_settings,
    ConfigLoadError,
)
from .validators import (
    ConfigValidationError,
    check_authors_non_empty,
    check_unique_author_emails,
    run_validations,
)

__all__ = [
    "Author",
    "FileConfig",
    "EnvSettings",
    "AppConfig",
    "load_config",
    "load_file_config",
    "load_env_settings",
    "ConfigLoadError",
    "ConfigValidationError",
    "check_authors_non_empty",
    "check_unique_author_emails",
    "run_validations",
]
