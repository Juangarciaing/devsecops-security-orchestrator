"""Twelve-Factor application configuration.

Required settings have no default, so `Settings()` raises `pydantic.ValidationError`
immediately if a required environment variable is missing — fail fast at process
startup, before any request is served.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str
    secret_key: str
    jwt_secret_key: str
    environment: str = "development"
    jwt_expiry_minutes: int = 30
    first_admin_email: str | None = None
    first_admin_password: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
