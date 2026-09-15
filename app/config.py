"""
app/config.py
Pydantic Settings — loaded from .env or environment variables.
"""
from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str = "sqlite+aiosqlite:///./linkedin_prospector.db"

    # Apollo Data
    apollo_api_key: Optional[str] = None

    # Gemini
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-1.5-flash"

    # App
    app_env: str = "development"
    log_level: str = "INFO"

    # Project 1 integration
    outreach_engine_db_url: str | None = Field(default=None)

    # HubSpot Integration
    hubspot_access_token: str | None = Field(default=None)

    @property
    def mock_mode(self) -> bool:
        """True when no Apollo key is set — uses fixture data."""
        return not self.apollo_api_key

    @property
    def llm_enabled(self) -> bool:
        """True when a Gemini key is configured."""
        return bool(self.gemini_api_key)

    @property
    def is_sqlite(self) -> bool:
        return "sqlite" in self.database_url.lower()


@lru_cache
def get_settings() -> Settings:
    return Settings()
