"""`orchestrator.workers.celery_app` — Celery app configuration (D1).

The module resolves broker/backend URLs from `Settings` at IMPORT time (the
standard Celery `-A module` pattern), so every test here (re)imports the
module AFTER monkeypatching env vars and clearing the settings cache, using
`importlib.reload` when the module was already imported by an earlier test.
"""

from __future__ import annotations

import importlib
import sys
from types import ModuleType

import pytest


def _import_celery_app(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    from orchestrator.infrastructure.config.settings import get_settings

    get_settings.cache_clear()

    module_name = "orchestrator.workers.celery_app"
    if module_name in sys.modules:
        return importlib.reload(sys.modules[module_name])
    return importlib.import_module(module_name)


def test_celery_app_falls_back_to_redis_url_when_celery_urls_unset(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
    monkeypatch.delenv("CELERY_RESULT_BACKEND", raising=False)

    module = _import_celery_app(monkeypatch)

    assert module.celery_app.conf.broker_url == "redis://localhost:6379/0"
    assert module.celery_app.conf.result_backend == "redis://localhost:6379/0"


def test_celery_app_prefers_explicit_celery_urls_over_redis_url(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://localhost:6379/3")
    monkeypatch.setenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/4")

    module = _import_celery_app(monkeypatch)

    assert module.celery_app.conf.broker_url == "redis://localhost:6379/3"
    assert module.celery_app.conf.result_backend == "redis://localhost:6379/4"


def test_celery_app_declares_scan_and_webhook_queues(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    module = _import_celery_app(monkeypatch)

    queue_names = {queue.name for queue in module.celery_app.conf.task_queues}
    assert queue_names == {"scan", "webhook"}
    assert module.celery_app.conf.task_default_queue == "scan"


def test_celery_app_routes_scan_task_to_scan_queue(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    module = _import_celery_app(monkeypatch)

    routes = module.celery_app.conf.task_routes
    assert routes["orchestrator.workers.tasks.process_scan.process_scan_task"] == {"queue": "scan"}
