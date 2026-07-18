"""`orchestrator.workers.celery_app` — Celery app configuration (D1).

The module resolves broker/backend URLs from `Settings` at IMPORT time (the
standard Celery `-A module` pattern), so every test here (re)imports the
module AFTER monkeypatching env vars and clearing the settings cache, using
`importlib.reload` when the module was already imported by an earlier test.
"""

from __future__ import annotations

import importlib
import os
import subprocess
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


def test_worker_process_registers_process_scan_task_without_manual_import() -> None:
    """Regression test for the cross-process task-registration gap found by
    live `docker compose up` verification (verify-report CRITICAL): a
    standalone worker process only ever imports
    `orchestrator.workers.celery_app` (via `celery -A
    orchestrator.workers.celery_app worker`) and MUST register
    `process_scan_task` on its own. It must NOT depend on the API router's
    lazy, request-time import of `orchestrator.workers.tasks.process_scan`
    (D4) — that only registers the task on the BACKEND process's app
    instance, never on a separate worker process's app instance.

    Runs in a genuinely FRESH subprocess/interpreter that imports ONLY
    `orchestrator.workers.celery_app` — never
    `orchestrator.workers.tasks.process_scan`, directly or transitively via
    any other already-imported test module — to faithfully reproduce what
    `celery -A orchestrator.workers.celery_app worker` sees on startup.
    Eager-mode/in-process tests (`task_always_eager=True`, `.apply()`)
    structurally cannot catch this class of bug because they always run in
    the same process/interpreter that already imported the task module.

    Explicitly calls `celery_app.loader.import_default_modules()` — the
    exact call `WorkController.__init__` makes (via
    `app.loader.init_worker()`, `celery/worker/worker.py`) when a real
    `celery -A ... worker` process boots — instead of starting a full
    worker, since merely importing the app module does not by itself
    trigger Celery's `include=[...]` module loading (that only happens on
    worker/beat bootstrap or `celery report`).
    """
    env = dict(os.environ)
    env.update(
        DATABASE_URL="postgresql://orchestrator:changeme@localhost:5432/orchestrator",
        REDIS_URL="redis://localhost:6379/0",
        SECRET_KEY="test-secret-key",
        JWT_SECRET_KEY="test-jwt-secret-key",
    )
    script = (
        "from orchestrator.workers.celery_app import celery_app\n"
        "celery_app.loader.import_default_modules()\n"
        "assert 'orchestrator.workers.tasks.process_scan.process_scan_task' "
        "in celery_app.tasks, sorted(celery_app.tasks.keys())\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr


def test_webhook_queue_is_declared_but_no_task_is_routed_to_it(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    """Explicit non-goal (spec): the `webhook` queue is configured/routable but
    inert — no task is registered against it in this module (reserved for
    Module 10)."""
    module = _import_celery_app(monkeypatch)

    queue_names = {queue.name for queue in module.celery_app.conf.task_queues}
    assert "webhook" in queue_names

    routed_queues = {route["queue"] for route in module.celery_app.conf.task_routes.values()}
    assert "webhook" not in routed_queues
