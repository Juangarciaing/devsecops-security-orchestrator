"""`process_scan_task` — manual phase-span coverage (Module 13a, tasks 3.1-4.10).

`run_async`/`_load_and_start`/`_checkout_and_scan`/`_complete_scan` are
monkeypatched to canned fakes for the span-shape/order tests below — these
tests exist to prove the SPAN SHAPE (names, chronological order, attributes)
`process_scan_task` emits around each phase without needing a real Postgres
or Docker socket. `test_process_scan_task.py` (integration) already covers
the real state-machine/persistence behavior end to end; duplicating that
here would be redundant.

The nesting test at the bottom calls the REAL `_checkout_and_scan` against a
mocked low-level `docker` client (same double `test_docker_container_runner.py`
and `test_git_checkout.py` already use) to prove `container.run`/`git.checkout`
spans actually nest under the `scan.checkout_and_scan` span when invoked
synchronously in the task body's thread — exactly how `process_scan_task`
calls it.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.value_objects.enums import ScannerType

if TYPE_CHECKING:
    from types import ModuleType

_TASK_ID = uuid.uuid4()
_SCAN_RUN_ID = uuid.uuid4()
_REPOSITORY_ID = uuid.uuid4()
# Deliberately shaped like a credential-bearing clone URL / a real branch ref
# — the threat-matrix test below proves NEITHER ever reaches a span.
_CLONE_URL = "https://x-access-token:s3cr3t-tok3n@example.com/acme-scan/widgets.git"
_REF = "refs/heads/feature/leaky-branch"
_HEAD_SHA = "deadbeef1234"


def _fake_run_async[T](coro_factory: Callable[[AsyncSession | None], Awaitable[T]]) -> T:
    return asyncio.run(coro_factory(None))  # type: ignore[arg-type]


async def _fake_load_and_start(
    _session: AsyncSession, _scan_task_id: uuid.UUID
) -> tuple[str, str, uuid.UUID, uuid.UUID, ScannerType]:
    return _CLONE_URL, _REF, _SCAN_RUN_ID, _REPOSITORY_ID, ScannerType.SECRETS


def _fake_checkout_and_scan(
    _clone_url: str,
    _ref: str,
    _scan_task_id: uuid.UUID,
    _scanner_type: ScannerType,
    _runner: object,
    _docker_client: object,
    _settings: object,
) -> tuple[str, list[Finding]]:
    return _HEAD_SHA, []


async def _fake_complete_scan(
    _session: AsyncSession,
    _scan_task_id: uuid.UUID,
    _scan_run_id: uuid.UUID,
    _repository_id: uuid.UUID,
    _head_sha: str,
    _findings: list[Finding],
) -> None:
    return None


def _run_task(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    from orchestrator.workers.tasks import process_scan

    monkeypatch.setattr(process_scan, "run_async", _fake_run_async)
    monkeypatch.setattr(process_scan, "_load_and_start", _fake_load_and_start)
    monkeypatch.setattr(process_scan, "_checkout_and_scan", _fake_checkout_and_scan)
    monkeypatch.setattr(process_scan, "_complete_scan", _fake_complete_scan)

    result = process_scan.process_scan_task.apply(
        args=(str(_TASK_ID),),
        kwargs={"docker_client": MagicMock()},
    )
    result.get()
    return process_scan


def test_process_scan_task_emits_a_load_and_start_span(
    monkeypatch: pytest.MonkeyPatch, valid_env: None, span_exporter: InMemorySpanExporter
) -> None:
    _run_task(monkeypatch)

    names = [span.name for span in span_exporter.get_finished_spans()]
    assert "scan.load_and_start" in names


def test_process_scan_task_emits_a_checkout_and_scan_span_with_scanner_type(
    monkeypatch: pytest.MonkeyPatch, valid_env: None, span_exporter: InMemorySpanExporter
) -> None:
    _run_task(monkeypatch)

    spans = {span.name: span for span in span_exporter.get_finished_spans()}
    assert spans["scan.checkout_and_scan"].attributes is not None
    assert spans["scan.checkout_and_scan"].attributes["scanner_type"] == "secrets"


def test_process_scan_task_emits_a_write_back_span_with_db_attributes(
    monkeypatch: pytest.MonkeyPatch, valid_env: None, span_exporter: InMemorySpanExporter
) -> None:
    _run_task(monkeypatch)

    spans = {span.name: span for span in span_exporter.get_finished_spans()}
    write_back_attrs = spans["scan.write_back"].attributes
    assert write_back_attrs is not None
    assert write_back_attrs["db.system"] == "postgresql"
    assert write_back_attrs["findings.count"] == 0
    assert write_back_attrs["repository.id"] == str(_REPOSITORY_ID)
    assert write_back_attrs["scan_run.id"] == str(_SCAN_RUN_ID)


def test_process_scan_task_phase_spans_occur_in_chronological_order(
    monkeypatch: pytest.MonkeyPatch, valid_env: None, span_exporter: InMemorySpanExporter
) -> None:
    _run_task(monkeypatch)

    phase_names = [
        span.name for span in span_exporter.get_finished_spans() if span.name.startswith("scan.")
    ]
    assert phase_names == ["scan.load_and_start", "scan.checkout_and_scan", "scan.write_back"]


def test_no_span_ever_carries_clone_url_ref_or_raw_finding_content(
    monkeypatch: pytest.MonkeyPatch, valid_env: None, span_exporter: InMemorySpanExporter
) -> None:
    """Threat matrix (spec/design): sensitive data in span attributes. Neither
    the resolved `clone_url` nor the VCS `ref` may ever appear as a span
    attribute key or value — allowlisted attributes are `scanner_type`,
    `db.system`, `findings.count`, `repository.id`, `scan_run.id` only."""
    _run_task(monkeypatch)

    disallowed_keys = {"clone_url", "ref"}
    for span in span_exporter.get_finished_spans():
        for key, value in (span.attributes or {}).items():
            assert key not in disallowed_keys
            if isinstance(value, str):
                assert _CLONE_URL not in value
                assert _REF not in value


def test_checkout_and_scan_container_and_checkout_spans_nest_under_the_task_span(
    monkeypatch: pytest.MonkeyPatch, valid_env: None, span_exporter: InMemorySpanExporter
) -> None:
    """Tasks 4.9/4.10: `container.run` (`DockerContainerRunner`) and
    `git.checkout` (`GitCheckout`) spans nest under `scan.checkout_and_scan`
    when `_checkout_and_scan` runs synchronously in the task body's thread —
    exactly how `process_scan_task` invokes it in production."""
    from orchestrator.infrastructure.config.settings import Settings
    from orchestrator.infrastructure.container.docker_container_runner import (
        DockerContainerRunner,
    )
    from orchestrator.workers.tasks.process_scan import _checkout_and_scan

    settings = Settings(
        _env_file=None,
        database_url="postgresql://x:x@localhost/x",
        redis_url="redis://localhost:6379/0",
        secret_key="s",
        jwt_secret_key="j",
    )
    docker_client = MagicMock()
    container = MagicMock()
    container.wait.return_value = {"StatusCode": 0}
    container.logs.return_value = b""
    docker_client.containers.run.return_value = container
    runner = DockerContainerRunner(client=docker_client)

    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("scan.checkout_and_scan") as task_span:
        _checkout_and_scan(
            _CLONE_URL, _REF, _TASK_ID, ScannerType.SECRETS, runner, docker_client, settings
        )

    task_span_id = task_span.get_span_context().span_id
    finished = span_exporter.get_finished_spans()

    checkout_spans = [span for span in finished if span.name == "git.checkout"]
    assert len(checkout_spans) == 1
    checkout_span = checkout_spans[0]
    assert checkout_span.parent is not None
    assert checkout_span.parent.span_id == task_span_id

    container_spans = [span for span in finished if span.name == "container.run"]
    assert len(container_spans) == 3  # clone, rev-parse, gitleaks scan
    for span in container_spans:
        assert span.parent is not None

    parent_ids = {span.parent.span_id for span in container_spans if span.parent is not None}
    # The clone/rev-parse container.run spans nest under git.checkout; the
    # scanner's own container.run nests directly under scan.checkout_and_scan.
    assert checkout_span.context is not None
    assert checkout_span.context.span_id in parent_ids
    assert task_span_id in parent_ids
