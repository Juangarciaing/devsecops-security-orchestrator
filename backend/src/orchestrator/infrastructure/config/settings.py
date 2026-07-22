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

    # Module 9 — opt-in CORS for a browser-hosted frontend served from a
    # different origin (e.g. local `npm run dev` at :5173 talking to this
    # API at :8000). Comma-separated list of exact allowed origins; empty
    # (the default) adds ZERO middleware and ZERO behavior change — no
    # deployment gets CORS headers unless it explicitly opts in.
    cors_allowed_origins: str = ""

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

    # Module 11 — pip-audit SCA scanner image, built locally from
    # `docker/pip-audit.Dockerfile` (which itself pins its `python:3.12-slim`
    # base by digest and `pip-audit` by exact version). Tag-only here,
    # mirroring how `scan_git_image`/`scan_container_image` are configured.
    scan_pip_audit_image: str = "pip-audit-scanner:local"

    # Module 11 — AST-based SAST scanner image, built locally from
    # `docker/sast-scanner.Dockerfile` (which pins its `python:3.12-slim`
    # base by digest and the `sast-scanner` source by exact commit SHA).
    # Tag-only here, mirroring `scan_pip_audit_image`.
    scan_sast_image: str = "sast-scanner:local"

    # Module 11 — Semgrep multi-language SAST scanner image, built locally
    # from `docker/semgrep.Dockerfile` (which pins its `python:3.12-slim`
    # base by digest, `semgrep` by exact version, and its rule packs at
    # build time). Tag-only here, mirroring `scan_sast_image`.
    scan_semgrep_image: str = "semgrep-scanner:local"

    # Module 10 — HMAC-SHA256 secret for verifying inbound GitHub webhook
    # deliveries. Nullable/fail-closed (D1): the app boots without it; the
    # signature verifier treats an unset secret as always-invalid, so every
    # delivery is 401-audited rather than accepted unverified.
    github_webhook_secret: str | None = None

    # Module 13a — OpenTelemetry distributed tracing. Opt-in via presence
    # (D1): an empty (the default) endpoint means tracing is fully off — no
    # TracerProvider is set, no exporter/thread/socket is created, and the
    # existing request/task pipeline is byte-for-byte unchanged. Mirrors the
    # `cors_allowed_origins`/`github_webhook_secret` opt-in-via-presence
    # precedent; neither field is required, so tracing can never block
    # application startup.
    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "orchestrator"


@lru_cache
def get_settings() -> Settings:
    return Settings()
