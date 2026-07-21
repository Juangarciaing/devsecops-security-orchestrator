"""Settings must fail fast at construction time when a required env var is missing."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestrator.infrastructure.config.settings import Settings


def test_settings_raises_when_database_url_missing(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert "database_url" in str(exc_info.value)


def test_settings_raises_when_redis_url_missing(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert "redis_url" in str(exc_info.value)


def test_settings_loads_successfully_when_all_required_vars_present(valid_env: None) -> None:
    settings = Settings(_env_file=None)

    assert settings.database_url == "postgresql://orchestrator:changeme@localhost:5432/orchestrator"
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.secret_key == "test-secret-key"
    assert settings.environment == "development"


def test_settings_raises_when_jwt_secret_key_missing(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert "jwt_secret_key" in str(exc_info.value)


def test_settings_jwt_expiry_minutes_defaults_to_30(valid_env: None) -> None:
    settings = Settings(_env_file=None)

    assert settings.jwt_expiry_minutes == 30


def test_settings_jwt_expiry_minutes_can_be_overridden(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    monkeypatch.setenv("JWT_EXPIRY_MINUTES", "120")

    settings = Settings(_env_file=None)

    assert settings.jwt_expiry_minutes == 120


def test_settings_celery_broker_url_defaults_to_none(valid_env: None) -> None:
    settings = Settings(_env_file=None)

    assert settings.celery_broker_url is None
    assert settings.celery_result_backend is None


def test_settings_celery_broker_url_can_be_overridden(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
    monkeypatch.setenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

    settings = Settings(_env_file=None)

    assert settings.celery_broker_url == "redis://localhost:6379/1"
    assert settings.celery_result_backend == "redis://localhost:6379/2"


def test_settings_scan_container_defaults(valid_env: None) -> None:
    """Module 6: hardened-container tuning knobs default sensibly (design's
    File Changes table) so a fresh checkout runs scans without extra config."""
    settings = Settings(_env_file=None)

    assert settings.scan_container_image.startswith("ghcr.io/gitleaks/gitleaks:")
    assert "@sha256:" in settings.scan_container_image
    assert settings.scan_git_image.startswith("alpine/git:")
    assert "@sha256:" in settings.scan_git_image
    assert settings.scan_memory_limit_mb == 512
    assert settings.scan_cpu_limit == 1.0
    assert settings.scan_pids_limit == 128
    assert settings.scan_timeout_seconds == 120


def test_settings_github_webhook_secret_defaults_to_none(valid_env: None) -> None:
    """Module 10 D1: unset secret is a valid boot state (fail-closed at
    verification time, not at startup)."""
    settings = Settings(_env_file=None)

    assert settings.github_webhook_secret is None


def test_settings_github_webhook_secret_can_be_overridden(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "a-real-secret")

    settings = Settings(_env_file=None)

    assert settings.github_webhook_secret == "a-real-secret"


def test_settings_otel_exporter_otlp_endpoint_defaults_to_off(valid_env: None) -> None:
    """Module 13a D1: empty endpoint (the default) means tracing is fully off —
    no exporter, zero behavior change to the existing request/task pipeline."""
    settings = Settings(_env_file=None)

    assert settings.otel_exporter_otlp_endpoint == ""
    assert settings.otel_service_name == "orchestrator"


def test_settings_otel_exporter_otlp_endpoint_can_be_overridden(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4317")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "orchestrator-api")

    settings = Settings(_env_file=None)

    assert settings.otel_exporter_otlp_endpoint == "http://jaeger:4317"
    assert settings.otel_service_name == "orchestrator-api"


def test_settings_scan_container_values_can_be_overridden(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    overridden_container_image = "ghcr.io/gitleaks/gitleaks:v8.99.0@sha256:" + "a" * 64
    overridden_git_image = "alpine/git:9.9.9@sha256:" + "b" * 64
    monkeypatch.setenv("SCAN_CONTAINER_IMAGE", overridden_container_image)
    monkeypatch.setenv("SCAN_GIT_IMAGE", overridden_git_image)
    monkeypatch.setenv("SCAN_MEMORY_LIMIT_MB", "1024")
    monkeypatch.setenv("SCAN_CPU_LIMIT", "2.5")
    monkeypatch.setenv("SCAN_PIDS_LIMIT", "256")
    monkeypatch.setenv("SCAN_TIMEOUT_SECONDS", "300")

    settings = Settings(_env_file=None)

    assert settings.scan_container_image == overridden_container_image
    assert settings.scan_git_image == overridden_git_image
    assert settings.scan_memory_limit_mb == 1024
    assert settings.scan_cpu_limit == 2.5
    assert settings.scan_pids_limit == 256
    assert settings.scan_timeout_seconds == 300
