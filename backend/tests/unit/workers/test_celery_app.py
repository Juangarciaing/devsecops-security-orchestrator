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
from collections.abc import Iterator
from types import ModuleType
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _clear_worker_process_init_receivers() -> Iterator[None]:
    """Every test in this module reloads `celery_app`, and the module
    re-registers its `worker_process_init`/`worker_process_shutdown` handlers
    at import time — without resetting each signal's receiver list between
    tests, repeated reloads would accumulate duplicate handlers and any test
    that `.send()`s a signal would observe N stale calls instead of exactly
    one."""
    from celery.signals import worker_process_init, worker_process_shutdown

    worker_process_init.receivers = []
    worker_process_shutdown.receivers = []
    yield
    worker_process_init.receivers = []
    worker_process_shutdown.receivers = []


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


def test_importing_celery_app_does_not_configure_tracing(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    """Module 13a D2 (fork-safety regression guard): merely importing
    `celery_app` (module-import time, i.e. the pre-fork parent process) MUST
    NOT initialize tracing — that would hand every forked worker child a
    broken, pre-fork-inherited exporter/thread. Tracing init is deferred to
    the `worker_process_init` signal, which fires per-child AFTER the fork."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4317")

    # Patch the ORIGIN module's functions, not `celery_app`'s imported alias:
    # `_import_celery_app` may `importlib.reload` the module, which re-runs
    # its top-level `from ...tracing import configure_tracing` statement —
    # that fresh `from import` re-binds whatever the origin module's
    # attribute currently is, so patching the origin here survives reload.
    with (
        patch(
            "orchestrator.infrastructure.observability.tracing.configure_tracing"
        ) as mock_configure,
        patch(
            "orchestrator.infrastructure.observability.tracing.instrument_celery"
        ) as mock_instrument,
    ):
        _import_celery_app(monkeypatch)

        mock_configure.assert_not_called()
        mock_instrument.assert_not_called()


def test_worker_process_init_signal_configures_tracing_and_instruments_celery(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    """Module 13a D2: the `worker_process_init` handler — fired in EACH
    forked worker child, never in the pre-fork parent — is what actually
    performs per-process tracing init."""
    from celery.signals import worker_process_init

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4317")

    with (
        patch(
            "orchestrator.infrastructure.observability.tracing.configure_tracing"
        ) as mock_configure,
        patch(
            "orchestrator.infrastructure.observability.tracing.instrument_celery"
        ) as mock_instrument,
    ):
        _import_celery_app(monkeypatch)

        worker_process_init.send(sender=None)

        mock_configure.assert_called_once_with("orchestrator-worker")
        mock_instrument.assert_called_once()


def test_worker_process_init_combines_otel_service_name_setting_with_worker_suffix(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    """Review WARNING: `Settings.otel_service_name` was dead config — this
    call site hardcoded the literal `"orchestrator-worker"` regardless of
    the setting. `configure_tracing` must receive the configured service
    name combined with a `-worker` role suffix, so changing
    `OTEL_SERVICE_NAME` actually changes the name reaching Jaeger's service
    list."""
    from celery.signals import worker_process_init

    monkeypatch.setenv("OTEL_SERVICE_NAME", "custom-service")

    with patch(
        "orchestrator.infrastructure.observability.tracing.configure_tracing"
    ) as mock_configure:
        _import_celery_app(monkeypatch)

        worker_process_init.send(sender=None)

        mock_configure.assert_called_once_with("custom-service-worker")


def test_worker_process_shutdown_signal_flushes_tracing(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    """Module 13a follow-up — counterpart to `worker_process_init`:
    `worker_process_shutdown` fires in EACH forked worker child on graceful
    shutdown (worker restart, rolling deploy) and must flush any spans
    buffered but not yet exported, the gap left by removing the SDK's
    `atexit`-based flush."""
    from celery.signals import worker_process_shutdown

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4317")

    with patch(
        "orchestrator.infrastructure.observability.tracing.shutdown_tracing"
    ) as mock_shutdown:
        _import_celery_app(monkeypatch)

        worker_process_shutdown.send(sender=None)

        mock_shutdown.assert_called_once()


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
