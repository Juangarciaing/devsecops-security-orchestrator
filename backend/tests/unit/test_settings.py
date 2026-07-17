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
