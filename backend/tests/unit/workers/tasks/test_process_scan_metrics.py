"""Committed worker-lifecycle metric hooks."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from celery.exceptions import Retry
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.value_objects.enums import ScannerType
from orchestrator.infrastructure.observability.metrics import _failure_category
from orchestrator.infrastructure.vcs.git_checkout import CheckoutFailedError

_TASK_ID = uuid.uuid4()
_RUN_ID = uuid.uuid4()
_REPOSITORY_ID = uuid.uuid4()


def _run_async[T](factory: Callable[[AsyncSession | None], Awaitable[T]]) -> T:
    return asyncio.run(factory(None))  # type: ignore[arg-type]


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    *,
    load: tuple[str, str, uuid.UUID, uuid.UUID, ScannerType, bool, bool],
    complete: tuple[bool, float] = (True, 30.0),
    checkout: object = ("head", []),
    failed: tuple[bool, ScannerType, float] = (True, ScannerType.SECRETS, 150.0),
) -> tuple[SimpleNamespace, dict[str, list[object]]]:
    from orchestrator.workers.tasks import process_scan

    metrics: dict[str, list[object]] = {
        key: [] for key in ("started", "retry", "terminal", "findings")
    }

    async def load_scan(
        _session: AsyncSession, _task_id: uuid.UUID
    ) -> tuple[str, str, uuid.UUID, uuid.UUID, ScannerType, bool, bool]:
        return load

    async def complete_scan(*_args: object) -> tuple[bool, float]:
        return complete

    async def mark_failed(*_args: object) -> tuple[bool, ScannerType, float]:
        return failed

    def checkout_scan(*_args: object) -> tuple[str, list[Finding]]:
        if isinstance(checkout, Exception):
            raise checkout
        return checkout  # type: ignore[return-value]

    monkeypatch.setattr(process_scan, "run_async", _run_async)
    monkeypatch.setattr(process_scan, "_load_and_start", load_scan)
    monkeypatch.setattr(process_scan, "_complete_scan", complete_scan)
    monkeypatch.setattr(process_scan, "_mark_failed", mark_failed)
    monkeypatch.setattr(process_scan, "_checkout_and_scan", checkout_scan)
    monkeypatch.setattr(process_scan, "record_scan_started", metrics["started"].append)
    monkeypatch.setattr(
        process_scan, "record_scan_retried", lambda *args: metrics["retry"].append(args)
    )
    monkeypatch.setattr(
        process_scan, "record_scan_terminal", lambda *args: metrics["terminal"].append(args)
    )
    monkeypatch.setattr(
        process_scan, "record_scan_findings", lambda *args: metrics["findings"].append(args)
    )
    monkeypatch.setattr(process_scan, "record_scanner_duration", lambda *_args: None)
    task = SimpleNamespace(request=SimpleNamespace(retries=0), retry=MagicMock())
    return task, metrics


def _invoke(task: object) -> None:
    from orchestrator.workers.tasks.process_scan import process_scan_task

    process_scan_task.run.__func__(task, str(_TASK_ID), docker_client=MagicMock())


def test_started_requires_committed_pending_transition_and_skips_terminal_delivery(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    terminal_load = ("url", "ref", _RUN_ID, _REPOSITORY_ID, ScannerType.SECRETS, False, True)
    task, metrics = _wire(monkeypatch, load=terminal_load)

    _invoke(task)

    assert metrics == {"started": [], "retry": [], "terminal": [], "findings": []}


def test_started_records_after_transition_but_terminal_metrics_require_terminal_commit(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    load = ("url", "ref", _RUN_ID, _REPOSITORY_ID, ScannerType.SECRETS, True, False)
    task, metrics = _wire(monkeypatch, load=load, complete=(False, 0.0))

    _invoke(task)

    assert metrics["started"] == [ScannerType.SECRETS]
    assert metrics["terminal"] == []
    assert metrics["findings"] == []


def test_completion_emits_terminal_findings_and_persisted_duration_after_commit(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    load = ("url", "ref", _RUN_ID, _REPOSITORY_ID, ScannerType.SECRETS, False, False)
    task, metrics = _wire(
        monkeypatch, load=load, complete=(True, 150.0), checkout=("head", [MagicMock()])
    )

    _invoke(task)

    assert metrics["terminal"] == [(ScannerType.SECRETS, "completed", "none", 150.0)]
    assert metrics["findings"] == [(ScannerType.SECRETS, 1)]


def test_nonretryable_failure_is_terminal_with_checkout_category_and_no_retry(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    load = ("url", "ref", _RUN_ID, _REPOSITORY_ID, ScannerType.SECRETS, False, False)
    task, metrics = _wire(monkeypatch, load=load, checkout=CheckoutFailedError("clone failed"))

    _invoke(task)

    assert task.retry.call_count == 0
    assert metrics["retry"] == []
    assert metrics["terminal"] == [(ScannerType.SECRETS, "failed", "checkout", 150.0)]


def test_retry_is_nonterminal_and_exhaustion_records_one_terminal_duration(
    monkeypatch: pytest.MonkeyPatch, valid_env: None
) -> None:
    from orchestrator.workers.tasks.process_scan import MAX_RETRIES, TransientScanError

    load = ("url", "ref", _RUN_ID, _REPOSITORY_ID, ScannerType.SECRETS, False, False)
    task, metrics = _wire(monkeypatch, load=load, checkout=RuntimeError("daemon unavailable"))
    task.retry.side_effect = Retry()

    with pytest.raises(Retry):
        _invoke(task)

    assert metrics["retry"] == [(ScannerType.SECRETS, "container_runtime")]
    assert metrics["terminal"] == []

    task.request.retries = MAX_RETRIES
    task.retry.side_effect = TransientScanError("daemon unavailable")
    _invoke(task)

    assert metrics["retry"] == [(ScannerType.SECRETS, "container_runtime")]
    assert metrics["terminal"] == [(ScannerType.SECRETS, "failed", "container_runtime", 150.0)]


def test_completed_terminal_uses_the_fixed_none_failure_category() -> None:
    assert _failure_category("none") == "none"
