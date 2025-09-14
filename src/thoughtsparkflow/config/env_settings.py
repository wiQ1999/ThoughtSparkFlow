from pydantic import AnyUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class EnvSettings(BaseSettings):
    wp_api_url: AnyUrl = Field(validation_alias="WP_API_URL")
    wp_user: str = Field(validation_alias="WP_USER")
    wp_password: str = Field(validation_alias="WP_PASSWORD")
    openai_api_key: str = Field(validation_alias="OPENAI_API_KEY")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )
