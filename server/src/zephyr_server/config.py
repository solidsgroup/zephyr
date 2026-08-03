from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(value: str) -> str:
    """Select the async PostgreSQL driver for URLs supplied by hosting providers."""
    if value.startswith("postgres://"):
        return value.replace("postgres://", "postgresql+asyncpg://", 1)
    if value.startswith("postgresql://"):
        return value.replace("postgresql://", "postgresql+asyncpg://", 1)
    return value


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ZEPHYR_",
        env_file=".env",
        extra="ignore",
    )

    database_url: str = "sqlite+aiosqlite:///./zephyr.db"

    @field_validator("database_url", mode="before")
    @classmethod
    def async_database_driver(cls, value: object) -> object:
        """Render supplies a synchronous PostgreSQL URL; the service uses asyncpg."""
        if isinstance(value, str):
            return normalize_database_url(value)
        return value


def database_url_from_environment() -> str:
    """Load only database configuration so migrations don't require app secrets."""
    return DatabaseSettings().database_url


class Settings(DatabaseSettings):
    env: str = "development"
    public_url: str = "http://localhost:8000"
    session_secret: str = "development-session-secret-change-me"
    token_pepper: str = "development-token-pepper-change-me"
    dev_auth: bool = False
    static_dir: Path | None = None

    google_client_id: str = ""
    google_client_secret: str = ""
    google_allowed_domain: str = "solids.group"

    artifact_store: Literal["disabled", "google_drive"] = "disabled"
    google_drive_folder_id: str = ""
    google_drive_service_account_json: str = ""
    download_url_ttl_seconds: int = 900

    @model_validator(mode="after")
    def validate_production(self) -> Settings:
        if self.env == "production":
            if self.dev_auth:
                raise ValueError("ZEPHYR_DEV_AUTH must be false in production")
            if len(self.session_secret) < 32 or len(self.token_pepper) < 32:
                raise ValueError("Production secrets must contain at least 32 characters")
            if not self.google_client_id or not self.google_client_secret:
                raise ValueError("Google OIDC credentials are required in production")
            if self.artifact_store != "google_drive":
                raise ValueError("Google Drive artifact storage is required in production")
            if not self.google_drive_folder_id or not self.google_drive_service_account_json:
                raise ValueError(
                    "Google Drive folder and service account are required in production"
                )
            try:
                credentials = json.loads(self.google_drive_service_account_json)
            except json.JSONDecodeError as error:
                raise ValueError("Google Drive service account must be valid JSON") from error
            required = {"client_email", "private_key", "token_uri"}
            if not isinstance(credentials, dict) or not required.issubset(credentials):
                raise ValueError("Google Drive service account JSON is missing required fields")
        return self

    @property
    def secure_cookies(self) -> bool:
        return self.public_url.startswith("https://")


@lru_cache
def get_settings() -> Settings:
    return Settings()
