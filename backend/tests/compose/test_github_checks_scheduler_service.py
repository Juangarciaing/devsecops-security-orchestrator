"""Compose contract for the Celery Beat scheduler service that drives the
GitHub Checks outbox sweep (github-checks-publisher PR7, design: "Deployment
topology"). Mirrors `test_prometheus_config.py`'s `docker compose config
--format json` pattern — asserts against the fully-resolved base stack, not
hand-parsed YAML.

Task 7.1's explicit test target: Beat's ABSENCE of the GitHub App private
key, never its presence. The design doc's summary table has one sloppy line
implying the secret mounts into "Beat/worker pods" — that line is WRONG per
the design's own repeated, more specific statement ("PEM is worker-only,
never Beat") and per `settings.py`'s own comment ("the worker re-reads it
fresh on every JWT mint... Beat never reads it at all"). These tests trust
that more specific statement.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[3]

_GITHUB_APP_SECRET_KEYS = {"GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY_FILE"}


def _compose_config() -> dict[str, Any]:
    result = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.yml", "config", "--format", "json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _volume_sources(service: dict[str, Any]) -> set[str]:
    return {volume.get("source", "") for volume in service.get("volumes", [])}


def test_scheduler_service_runs_a_single_celery_beat_replica() -> None:
    services = _compose_config()["services"]

    assert "scheduler" in services
    assert services["scheduler"]["command"] == [
        "celery",
        "-A",
        "orchestrator.workers.celery_app",
        "beat",
        "-l",
        "info",
        "-s",
        "/tmp/celerybeat-schedule",
    ]


def test_scheduler_never_references_the_github_app_private_key() -> None:
    scheduler = _compose_config()["services"]["scheduler"]

    environment = scheduler.get("environment", {})
    assert _GITHUB_APP_SECRET_KEYS.isdisjoint(environment)
    assert not any(source.endswith("/secrets") for source in _volume_sources(scheduler))


def test_worker_consumes_both_the_scan_and_github_checks_queues() -> None:
    worker = _compose_config()["services"]["worker"]

    assert worker["command"] == [
        "celery",
        "-A",
        "orchestrator.workers.celery_app",
        "worker",
        "-Q",
        "scan,github_checks",
        "-l",
        "info",
    ]


def test_only_the_worker_service_mounts_the_github_app_secret_directory() -> None:
    services = _compose_config()["services"]

    worker_sources = _volume_sources(services["worker"])
    assert any(source.endswith("/secrets") for source in worker_sources)

    for name, service in services.items():
        if name == "worker":
            continue
        other_sources = _volume_sources(service)
        assert not any(source.endswith("/secrets") for source in other_sources)
