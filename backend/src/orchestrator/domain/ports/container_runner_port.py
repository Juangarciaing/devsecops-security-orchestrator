"""`ContainerRunnerPort` — contract for launching one hardened, ephemeral container.

Framework-free: this module MUST NOT import the `docker` SDK (or any other
container-runtime library) — only the concrete adapter
(`infrastructure.container.docker_container_runner`) does that. Typed with
plain dataclasses only, matching the other framework-free ports in this
package (`ScanRunPort`, `ScanTaskPort`, ...).

Synchronous by design (Module 6 D3): container orchestration is blocking I/O
(the `docker` SDK itself is sync). Callers invoke `.run()` OUTSIDE any async
DB session/event loop — see `workers/tasks/process_scan.py`'s split between
`run_async` (DB) and this port (containers).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    """Resource ceilings applied to one container run.

    `nano_cpus` is already in Docker's native "billionths of a CPU" unit
    (e.g. 1 full CPU == 1_000_000_000) — callers convert from a human
    `Settings.scan_cpu_limit` float before constructing this.
    """

    memory_mb: int
    nano_cpus: int
    pids_limit: int


@dataclass(frozen=True, slots=True)
class RunResult:
    """Outcome of one `ContainerRunnerPort.run()` call."""

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool


class ContainerRunnerPort(ABC):
    """Contract for running one hardened, ephemeral container to completion.

    A single `.run()` call launches exactly one container against a named
    Docker volume, blocks until it exits or the wall-clock timeout elapses,
    and guarantees the container is removed before returning — success,
    failure, or timeout. Implementations MUST NOT leave orphaned containers.
    """

    @abstractmethod
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
        """Run `image` with an argv-only `command` (never a shell string).

        `volume_name` (a pre-existing named Docker volume, not a host bind
        mount — sibling containers cannot resolve worker-local paths) is
        mounted at `mount_path`, read-only iff `read_only_mount`. The
        container's network is disabled (`network_mode="none"`) iff
        `network_disabled`; otherwise the default bridge network is used.

        Implementations MUST launch the container as a non-root user with
        `--read-only` rootfs, `cap_drop=["ALL"]`, `no-new-privileges`, and
        the given `limits`. On `timeout_seconds` elapsing, implementations
        MUST SIGKILL the container and return `RunResult(timed_out=True)`.
        The container MUST be force-removed in all cases (success, failure,
        timeout) before `.run()` returns.
        """
