from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ZEPHYR_",
        env_file=".env",
        extra="ignore",
    )

    env: str = "development"
    database_url: str = "sqlite+aiosqlite:///./zephyr.db"
    public_url: str = "http://localhost:8000"
    session_secret: str = "development-session-secret-change-me"
    token_pepper: str = "development-token-pepper-change-me"
    dev_auth: bool = False
    static_dir: Path | None = None

    google_client_id: str = ""
    google_client_secret: str = ""
    google_allowed_domain: str = "solids.group"

    s3_endpoint_url: str | None = None
    s3_public_endpoint_url: str | None = None
    s3_region: str = "auto"
    s3_bucket: str = "zephyr"
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    upload_url_ttl_seconds: int = 900
    download_url_ttl_seconds: int = 900

    @field_validator("database_url", mode="before")
    @classmethod
    def async_database_driver(cls, value: object) -> object:
        """Render supplies a synchronous PostgreSQL URL; the service uses asyncpg."""
        if isinstance(value, str):
            if value.startswith("postgres://"):
                return value.replace("postgres://", "postgresql+asyncpg://", 1)
            if value.startswith("postgresql://"):
                return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    @model_validator(mode="after")
    def validate_production(self) -> Settings:
        if self.env == "production":
            if self.dev_auth:
                raise ValueError("ZEPHYR_DEV_AUTH must be false in production")
            if len(self.session_secret) < 32 or len(self.token_pepper) < 32:
                raise ValueError("Production secrets must contain at least 32 characters")
            if not self.google_client_id or not self.google_client_secret:
                raise ValueError("Google OIDC credentials are required in production")
            if (
                not self.s3_endpoint_url
                or not self.s3_access_key_id
                or not self.s3_secret_access_key
            ):
                raise ValueError("S3-compatible object storage is required in production")
        return self

    @property
    def secure_cookies(self) -> bool:
        return self.public_url.startswith("https://")


@lru_cache
def get_settings() -> Settings:
    return Settings()
