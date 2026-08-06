"""`sweep_github_check_publications_task`'s disabled-flag fail-closed gate
(github-checks-publisher PR4, design: "Dispatch and lease" PR4->PR5
boundary). No delivery call exists yet — see `github_checks.py`'s module
docstring for the exact PR4->PR5 scope boundary.

`github_checks` (like `process_scan`) transitively imports `celery_app`,
which resolves `Settings` at MODULE IMPORT time — imported lazily inside
each test, after `valid_env` sets the required env vars, mirroring
`test_process_scan.py`'s existing precedent.
"""

from __future__ import annotations

import pytest

from orchestrator.infrastructure.config.settings import Settings


def _settings_with_delivery(*, enabled: bool) -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql://x:x@localhost/x",
        redis_url="redis://localhost:6379/0",
        secret_key="s",
        jwt_secret_key="j",
        github_checks_delivery_enabled=enabled,
    )


def test_disabled_delivery_flag_returns_zero_without_calling_run_async(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    """PR4->PR5 boundary: while `github_checks_delivery_enabled` is `False`
    (default), the sweep MUST return before `run_async`/`claim_due` is ever
    invoked — zero DB session, zero auth, zero network I/O."""
    from orchestrator.workers.tasks import github_checks

    def _explode(_coro_factory: object) -> int:
        raise AssertionError("run_async must not be called while delivery is disabled")

    monkeypatch.setattr(
        github_checks, "get_settings", lambda: _settings_with_delivery(enabled=False)
    )
    monkeypatch.setattr(github_checks, "run_async", _explode)

    result = github_checks.sweep_github_check_publications_task.apply()

    assert result.result == 0


def test_enabled_delivery_flag_delegates_to_run_async_with_the_claim_result(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    """Triangulation: flipping the flag on must actually reach `run_async`
    (proving the gate branches on the setting, not a hardcoded early
    return), and the task must surface whatever `run_async` resolves to."""
    from orchestrator.workers.tasks import github_checks

    captured: dict[str, object] = {}

    def _fake_run_async(coro_factory: object) -> int:
        captured["coro_factory"] = coro_factory
        return 3

    monkeypatch.setattr(
        github_checks, "get_settings", lambda: _settings_with_delivery(enabled=True)
    )
    monkeypatch.setattr(github_checks, "run_async", _fake_run_async)

    result = github_checks.sweep_github_check_publications_task.apply()

    assert result.result == 3
    assert callable(captured["coro_factory"])


def test_sweep_owner_id_combines_worker_hostname_and_task_id(valid_env: None) -> None:
    """`claim_due`'s owner-CAS needs a stable-per-invocation identifier —
    proves it is derived from Celery's own request context, not a fixed
    literal that would collide across concurrent sweeps."""
    from orchestrator.workers.tasks import github_checks

    class _FakeRequest:
        hostname = "worker-1"
        id = "task-abc"

    class _FakeTask:
        request = _FakeRequest()

    owner = github_checks._sweep_owner_id(_FakeTask())  # type: ignore[arg-type]

    assert owner == "worker-1:task-abc"
