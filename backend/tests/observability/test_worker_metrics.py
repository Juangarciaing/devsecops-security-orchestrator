"""Worker-owned Prometheus lifecycle and prefork collection contracts."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from orchestrator.infrastructure.container.docker_container_runner import container_metric_outcome
from orchestrator.infrastructure.observability.metrics import (
    STALE_WORKER_SECONDS,
    cleanup_stale_worker_files,
)


def test_worker_lifecycle_metrics_use_multiprocess_registry_and_bounded_labels(
    tmp_path: Path,
) -> None:
    exposition = _worker_exposition(tmp_path, "container_runtime")

    assert 'orchestrator_scan_started_total{queue="scan",scanner_type="secrets"} 1.0' in exposition
    assert 'failure_category="container_runtime"' in exposition
    assert (
        'orchestrator_scan_terminal_total{failure_category="timeout",outcome="failed",'
        in exposition
    )
    assert 'orchestrator_scan_duration_seconds_bucket{le="15.0",outcome="failed",' in exposition
    assert 'orchestrator_scan_findings_total{scanner_type="secrets"} 2.0' in exposition


def test_worker_metrics_do_not_expose_exception_or_scan_identifiers(tmp_path: Path) -> None:
    unsafe_error = "https://git.example/private.git ref deadbeef scan 123"

    exposition = _worker_exposition(tmp_path, unsafe_error)

    assert unsafe_error not in exposition
    assert 'failure_category="unknown"' in exposition


def test_stale_worker_cleanup_removes_dead_or_old_pid_files(tmp_path: Path) -> None:
    stale = tmp_path / "gauge_livesum_10001.db"
    live = tmp_path / f"gauge_livesum_{os.getpid()}.db"
    stale.write_bytes(b"stale")
    live.write_bytes(b"live")
    stale_at = datetime.now(UTC) - timedelta(seconds=STALE_WORKER_SECONDS + 1)
    os.utime(stale, (stale_at.timestamp(), stale_at.timestamp()))

    removed = cleanup_stale_worker_files(tmp_path, now=datetime.now(UTC))

    assert removed == {10001}
    assert not stale.exists()
    assert live.exists()


def test_logical_scan_duration_preserves_original_start_across_retry(valid_env: None) -> None:
    from orchestrator.workers.tasks.process_scan import logical_scan_duration_seconds

    original_start = datetime(2026, 7, 23, 12, 0, 0)
    completed_after_retry = datetime(2026, 7, 23, 12, 2, 30)

    assert logical_scan_duration_seconds(original_start, completed_after_retry) == 150.0


def test_container_metric_outcome_is_a_bounded_taxonomy() -> None:
    assert container_metric_outcome(timed_out=False) == "success"
    assert container_metric_outcome(timed_out=True) == "timeout"


def _worker_exposition(directory: Path, category: str) -> str:
    script = """
from prometheus_client import generate_latest
from orchestrator.domain.value_objects.enums import ScannerType
from orchestrator.infrastructure.observability.metrics import (
    build_worker_scrape_registry, record_container_duration, record_scan_findings,
    record_scan_retried, record_scan_started, record_scan_terminal, record_scanner_duration,
)
record_scan_started(ScannerType.SECRETS)
record_scan_retried(ScannerType.SECRETS, CATEGORY)
record_scan_terminal(ScannerType.SECRETS, 'failed', 'timeout', 15.0)
record_scanner_duration(ScannerType.SECRETS, 'timeout', 1.5)
record_container_duration('timeout', 0.5)
record_scan_findings(ScannerType.SECRETS, 2)
print(generate_latest(build_worker_scrape_registry()).decode())
""".replace("CATEGORY", repr(category))
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "PROMETHEUS_MULTIPROC_DIR": str(directory)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout
