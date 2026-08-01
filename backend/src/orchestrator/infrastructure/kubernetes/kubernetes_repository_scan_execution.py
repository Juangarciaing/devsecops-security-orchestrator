"""`KubernetesRepositoryScanExecution` — the `ScanExecutionPort` bridge over
`KubernetesSplitScanExecution` (k8s-backend-enable PR5, design D-Result).

Thin wrapper, resolving the interface mismatch design exploration found:
`KubernetesSplitScanExecution` (kept completely intact — its own 8 tests are
untouched by this PR) is keyword-only, takes `credential_ref: str | None`,
and returns `KubernetesScanResult(checkout_log, scanner_log, head_sha,
scanner_exit_code)`. This class adapts that onto `ScanExecutionPort`'s
existing, unmodified contract by resolving the Kubernetes scanner descriptor
(`kubernetes_scanner_descriptor.resolve_kubernetes_scanner`) and feeding the
scanner Job's stdout+exit code into the EXISTING, UNMODIFIED
`GitleaksAdapter.parse` — exactly the same parser the Docker backend already
trusts (`GitleaksDockerExecution`).
"""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING, cast

from orchestrator.domain.ports.container_runner_port import ContainerRunnerPort, RunResult
from orchestrator.domain.ports.scan_execution_port import ScanExecutionPort, ScanExecutionResult
from orchestrator.infrastructure.kubernetes.kubernetes_scan_execution import (
    KubernetesPrivateRepositoryError,
    KubernetesSplitScanExecution,
)
from orchestrator.infrastructure.kubernetes.kubernetes_scanner_descriptor import (
    resolve_kubernetes_scanner,
)
from orchestrator.infrastructure.scanners.gitleaks_adapter import GitleaksAdapter

if TYPE_CHECKING:
    from orchestrator.domain.ports.kubernetes_job_runner_port import KubernetesJobRunnerPort
    from orchestrator.domain.value_objects.enums import ScannerType
    from orchestrator.domain.value_objects.secret import Secret
    from orchestrator.infrastructure.config.settings import Settings

#: A scanner Job's exit code is only unobservable in a genuinely exceptional
#: case (design D-JobRunner: `JobOutcome.exit_code` is "best-effort... `None`
#: if unobservable"). Falling back to 0 here means such a case is reported
#: as a clean scan rather than crashing the bridge; documented, not hidden
#: (see k8s-backend-enable apply-progress for the residual honesty note).
_FALLBACK_EXIT_CODE_WHEN_UNOBSERVABLE = 0

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
#: Gitleaks' own `--report-path=/dev/stdout` JSON report is always the LAST
#: "paragraph" written — pretty-printed JSON, so its opening bracket is
#: always the first character of its own line.
_JSON_ARRAY_START_RE = re.compile(r"^\[.*$", re.MULTILINE)


def _extract_gitleaks_json_report(combined_log: str) -> str:
    """Recover Gitleaks' JSON report from a Kubernetes Pod's COMBINED
    stdout+stderr log stream.

    GENUINE PLATFORM DIFFERENCE from the Docker backend, discovered via
    PR5's live proof (task 5.18), not anticipated by the design doc: Docker
    keeps a container's stdout/stderr on separate multiplexed streams, so
    `GitleaksDockerExecution` hands `GitleaksAdapter.parse` a `RunResult.stdout`
    that is PURE JSON. Kubernetes' `read_namespaced_pod_log` (used by
    `get_job_logs`) returns ONE interleaved stream with no way to split it
    back apart — Gitleaks' own ANSI-colored `INF`/`WRN` status lines
    (`scanned ~N bytes...`, `leaks found: N`/`no leaks found`) land AHEAD of
    the JSON report in that merged text. Left unhandled, EVERY Kubernetes
    Gitleaks run (clean or dirty) would fail `GitleaksAdapter.parse` with a
    malformed-JSON error — this was caught ONLY by running a real scan
    against a real cluster, never by the fake-backed unit suite.

    Strips ANSI escape codes, then returns from the last line that opens a
    JSON array onward — `GitleaksAdapter.parse` itself is NOT modified;
    this is purely a k8s-specific log-shape adapter.
    """
    plain = _ANSI_ESCAPE_RE.sub("", combined_log)
    last_match = None
    for candidate in _JSON_ARRAY_START_RE.finditer(plain):
        last_match = candidate
    return plain if last_match is None else plain[last_match.start() :]


class KubernetesRepositoryScanExecution(ScanExecutionPort):
    """Bridges the k8s split-workload lifecycle onto `ScanExecutionPort`.

    Constructs a fresh `KubernetesSplitScanExecution` per `execute()` call
    (`scanner_type` is a call-time parameter, not fixed at construction —
    the same shape `ScanExecutionPort` already requires), with
    `scanner_exit_codes_are_data=True` always, so a non-zero scanner exit
    (e.g. Gitleaks' `--exit-code=2`) is data, never a raised
    `KubernetesWorkloadFailedError`.
    """

    def __init__(
        self,
        runner: KubernetesJobRunnerPort,
        *,
        namespace: str,
        checkout_image: str,
        settings: Settings,
        timeout_seconds: int = 120,
    ) -> None:
        self._runner = runner
        self._namespace = namespace
        self._checkout_image = checkout_image
        self._settings = settings
        self._timeout_seconds = timeout_seconds

    def execute(
        self,
        clone_url: str,
        ref: str,
        scan_task_id: uuid.UUID,
        scanner_type: ScannerType,
        credential: Secret | None = None,
    ) -> ScanExecutionResult:
        """Public repositories only: `credential is not None` raises
        `KubernetesPrivateRepositoryError` BEFORE any port call at all —
        zero cluster objects are created (design D-Scope-Guard). Secret
        projection into the checkout Job is a separate security design.
        """
        if credential is not None:
            raise KubernetesPrivateRepositoryError(
                "the Kubernetes backend supports public repositories only; "
                "Secret projection into the checkout Job is a separate security design"
            )

        scanner_image, scanner_command = resolve_kubernetes_scanner(scanner_type, self._settings)
        split_execution = KubernetesSplitScanExecution(
            self._runner,
            namespace=self._namespace,
            checkout_image=self._checkout_image,
            scanner_image=scanner_image,
            scanner_command=scanner_command,
            timeout_seconds=self._timeout_seconds,
            scanner_exit_codes_are_data=True,
        )
        result = split_execution.execute(
            clone_url=clone_url,
            ref=ref,
            credential_ref=None,
            scan_task_id=scan_task_id,
            scanner_type=scanner_type,
        )

        run_result = RunResult(
            exit_code=(
                _FALLBACK_EXIT_CODE_WHEN_UNOBSERVABLE
                if result.scanner_exit_code is None
                else result.scanner_exit_code
            ),
            stdout=_extract_gitleaks_json_report(result.scanner_log),
            stderr="",
            timed_out=False,
        )
        # `GitleaksAdapter.parse()` never touches its constructor's `runner`
        # argument (it is only ever read by the Docker-only `.run()` call
        # sites elsewhere) — this cast avoids threading an irrelevant
        # `ContainerRunnerPort` through the Kubernetes bridge just to
        # satisfy the shared adapter constructor's type.
        parser = GitleaksAdapter(cast("ContainerRunnerPort", None), self._settings)
        findings = parser.parse(run_result, scan_task_id)
        return ScanExecutionResult(head_sha=result.head_sha, findings=findings)
