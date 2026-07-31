"""`require_realtime_enabled` — the 503 gate (design D-Gate) that MUST
resolve before any auth/DB work, and `get_relay` (`app.state` accessor)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from orchestrator.api.v1.dependencies.realtime import get_relay, require_realtime_enabled
from orchestrator.api.v1.errors.problem import ProblemException
from orchestrator.infrastructure.config.settings import Settings


def _settings(*, realtime_enabled: bool) -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql://u:p@localhost/db",
        redis_url="redis://localhost:6379/0",
        secret_key="s",
        jwt_secret_key="j",
        realtime_enabled=realtime_enabled,
    )


def test_require_realtime_enabled_raises_503_when_disabled() -> None:
    with pytest.raises(ProblemException) as exc_info:
        asyncio.run(require_realtime_enabled(settings=_settings(realtime_enabled=False)))

    assert exc_info.value.status_code == 503


def test_require_realtime_enabled_is_a_noop_when_enabled() -> None:
    asyncio.run(require_realtime_enabled(settings=_settings(realtime_enabled=True)))  # no raise


def test_get_relay_reads_from_app_state() -> None:
    request = MagicMock()
    request.app.state.scan_event_relay = "the-relay"

    assert get_relay(request) == "the-relay"
