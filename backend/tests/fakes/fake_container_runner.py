"""`FakeContainerRunner` — in-memory `ContainerRunnerPort` test double.

Records every `.run()` call's kwargs and returns a scripted `RunResult`
queue (one entry per call, in order). Used by `GitCheckout`, the future
Gitleaks adapter (PR2), and `process_scan_task` (PR3) unit tests that need
to script container outcomes (clean scan, leaks found, bad-ref failure,
timeout, ...) WITHOUT a real Docker socket.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from orchestrator.domain.ports.container_runner_port import (
    ContainerRunnerPort,
    ResourceLimits,
    RunResult,
)

_DEFAULT_RESULT = RunResult(exit_code=0, stdout="", stderr="", timed_out=False)


@dataclass(frozen=True, slots=True)
class RecordedRun:
    """One recorded `.run()` invocation, for call-shape assertions in tests."""

    image: str
    command: list[str]
    volume_name: str
    mount_path: str
    read_only_mount: bool
    network_disabled: bool
    limits: ResourceLimits
    timeout_seconds: int


@dataclass(slots=True)
class FakeContainerRunner(ContainerRunnerPort):
    """In-memory `ContainerRunnerPort`. Script results via the constructor or `.script()`."""

    calls: list[RecordedRun] = field(default_factory=list)
    _results: list[RunResult] = field(default_factory=list, repr=False)

    def script(self, *results: RunResult) -> None:
        """Append `results` to the scripted-response queue, consumed in order."""
        self._results.extend(results)

    def run(
        self,
        *,
        image: str,
        command: list[str],
        volume_name: str,
        mount_path: str,
        read_only_mount: bool,
        network_disabled: bool,
        limits: ResourceLimits,
        timeout_seconds: int,
    ) -> RunResult:
        self.calls.append(
            RecordedRun(
                image=image,
                command=list(command),
                volume_name=volume_name,
                mount_path=mount_path,
                read_only_mount=read_only_mount,
                network_disabled=network_disabled,
                limits=limits,
                timeout_seconds=timeout_seconds,
            )
        )
        if self._results:
            return self._results.pop(0)
        return _DEFAULT_RESULT
