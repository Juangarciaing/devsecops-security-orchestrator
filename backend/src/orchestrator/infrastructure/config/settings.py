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
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None

    # Module 6 — hardened scanner-container execution. Both images are
    # tag+digest-pinned (confirmed against the registry at implementation
    # time via `docker pull`/`docker inspect`) so a fresh checkout cannot
    # silently drift to a newer, unaudited image build.
    scan_container_image: str = (
        "ghcr.io/gitleaks/gitleaks:v8.30.1"
        "@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f"
    )
    scan_git_image: str = (
        "alpine/git:2.54.0@sha256:697cb1c85aefc5724febaec2202a974e0d66f6abb6be91a9a86d0c8757af692a"
    )
    scan_memory_limit_mb: int = 512
    scan_cpu_limit: float = 1.0
    scan_pids_limit: int = 128
    scan_timeout_seconds: int = 120


@lru_cache
def get_settings() -> Settings:
    return Settings()
