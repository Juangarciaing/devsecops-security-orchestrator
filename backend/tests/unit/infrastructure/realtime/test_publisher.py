"""`publish_scan_status` — never raises, never retries, lazy fork-safe client."""

from __future__ import annotations

import logging
import uuid
from unittest.mock import MagicMock

import pytest

import orchestrator.infrastructure.realtime.publisher as publisher_module
from orchestrator.domain.value_objects.enums import ScanRunStatus
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.realtime.publisher import publish_scan_status


def _settings(*, realtime_enabled: bool) -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql://u:p@localhost/db",
        redis_url="redis://localhost:6379/0",
        secret_key="s",
        jwt_secret_key="j",
        realtime_enabled=realtime_enabled,
    )


def test_disabled_settings_never_construct_a_client(monkeypatch: pytest.MonkeyPatch) -> None:
    exploding_factory = MagicMock(side_effect=AssertionError("must not be called"))
    monkeypatch.setattr(publisher_module, "_build_client", exploding_factory)

    publish_scan_status(
        uuid.uuid4(), ScanRunStatus.RUNNING, settings=_settings(realtime_enabled=False)
    )

    exploding_factory.assert_not_called()


def test_enabled_and_redis_raising_returns_none_and_logs_once(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fake_client = MagicMock()
    fake_client.publish.side_effect = RuntimeError("connection refused")
    monkeypatch.setattr(publisher_module, "_build_client", MagicMock(return_value=fake_client))

    with caplog.at_level(logging.WARNING):
        result = publish_scan_status(
            uuid.uuid4(), ScanRunStatus.COMPLETED, settings=_settings(realtime_enabled=True)
        )

    assert result is None
    assert sum("realtime publish failed" in record.message for record in caplog.records) == 1


def test_client_is_built_lazily_not_at_import(monkeypatch: pytest.MonkeyPatch) -> None:
    build_calls: list[Settings] = []

    def _tracking_build(settings: Settings) -> MagicMock:
        build_calls.append(settings)
        return MagicMock()

    monkeypatch.setattr(publisher_module, "_build_client", _tracking_build)
    assert build_calls == []

    publish_scan_status(
        uuid.uuid4(), ScanRunStatus.FAILED, settings=_settings(realtime_enabled=True)
    )

    assert len(build_calls) == 1


def test_publishes_to_the_scan_channel_with_the_encoded_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = MagicMock()
    monkeypatch.setattr(publisher_module, "_build_client", MagicMock(return_value=fake_client))
    scan_run_id = uuid.uuid4()

    publish_scan_status(
        scan_run_id, ScanRunStatus.RUNNING, settings=_settings(realtime_enabled=True)
    )

    fake_client.publish.assert_called_once()
    channel, payload = fake_client.publish.call_args.args
    assert channel == f"scan:{scan_run_id}:events"
    assert '"status": "running"' in payload or '"status":"running"' in payload
