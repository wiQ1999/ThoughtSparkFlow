from __future__ import annotations
from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel, ValidationError
from .schemas import FileConfig
from .env_settings import EnvSettings

class ConfigLoadError(Exception):
    """The configuration loading error.

    Args:
        Exception (Exception): The original exception.
    """

def load_file_config(path: str | Path = "config.yaml") -> FileConfig:
    """Loads and validates the YAML config file into a FileConfig object.

    Args:
        path (str | Path, optional): The path to the config file. Defaults to "config.yaml".

    Raises:
        ConfigLoadError: If the config file is missing or invalid.

    Returns:
        FileConfig: The validated configuration settings.
    """
    p = Path(path)
    if not p.exists():
        raise ConfigLoadError(f"Missing config file: {p.resolve()}")
    try:
        text = p.read_text(encoding="utf-8")
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise ConfigLoadError(f"YAML parse error in {p}: {e}") from e
    try:
        return FileConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigLoadError("Invalid YAML config:\n" + str(e)) from e

def load_env_settings() -> EnvSettings:
    """Loads and validates the environment settings from .env.

    Raises:
        ConfigLoadError: If the environment settings are invalid.

    Returns:
        EnvSettings: The validated environment settings.
    """
    try:
        return EnvSettings()
    except ValidationError as e:
        raise ConfigLoadError("Invalid environment settings .env:\n" + str(e)) from e

class AppConfig(BaseModel):
    """Application configuration settings.

    Args:
        BaseModel (BaseModel): Pydantic base model for data validation.
    """
    env: EnvSettings
    file: FileConfig

def load_config(file_path: Optional[str | Path] = None) -> AppConfig:
    """Loads and validates the environment and application configuration.

    Args:
        file_path (Optional[str  |  Path], optional): The path to the config file. Defaults to None.

    Returns:
        AppConfig: The validated application configuration.
    """
    env = load_env_settings()
    file = load_file_config(file_path) if file_path else load_file_config()
    return AppConfig(env=env, file=file)
