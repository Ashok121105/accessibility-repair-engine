from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    is_render: bool = Field(default=False, validation_alias="RENDER")
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    frontend_origin: str = "http://localhost:5173"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    openai_api_key: str | None = None
    openai_model: str | None = None

    @property
    def is_production(self) -> bool:
        return self.is_render or self.app_env.strip().casefold() not in {
            "development",
            "dev",
            "local",
        }

    @field_validator("gemini_api_key", mode="before")
    @classmethod
    def normalize_empty_gemini_key(cls, value: str | None) -> str | None:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("gemini_model", mode="before")
    @classmethod
    def normalize_empty_gemini_model(cls, value: str | None) -> str:
        if isinstance(value, str) and not value.strip():
            return "gemini-2.5-flash"
        return value or "gemini-2.5-flash"

    @field_validator("openai_api_key", "openai_model", mode="before")
    @classmethod
    def normalize_empty_openai_settings(cls, value: str | None) -> str | None:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
