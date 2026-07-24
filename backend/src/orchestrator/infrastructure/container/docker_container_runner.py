"""`DockerContainerRunner` — `docker` Python SDK implementation of `ContainerRunnerPort`.

One `.run()` call launches exactly one hardened, ephemeral container against
a pre-existing named Docker volume, blocks until it exits or the wall-clock
timeout elapses, and force-removes it before returning — success, failure,
or timeout (Module 6 spec: "Wall-Clock Timeout Enforcement", "Hardened
Ephemeral Container Execution").
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import docker
import requests.exceptions
import urllib3.exceptions
from opentelemetry import trace

from orchestrator.domain.ports.container_runner_port import (
    ContainerRunnerPort,
    ResourceLimits,
    RunResult,
)

if TYPE_CHECKING:
    from docker import DockerClient

# Fixed, high, non-root UID:GID (matches `distroless`/`nonroot`-style images'
# conventional nobody UID). The launched image need not declare this user in
# its own `/etc/passwd` — Docker allows running as an arbitrary numeric UID.
_NONROOT_USER = "65532:65532"
_TMPFS_MOUNT_OPTS = "rw,noexec,nosuid,size=64m"
#: Module 11 D7b: opt-in relaxation for callers that pass `tmp_exec=True`
#: (pip-audit only, as of this module) — every other caller keeps the
#: strict `noexec` default above unchanged.
_TMPFS_MOUNT_OPTS_EXEC = "rw,exec,nosuid,size=64m"


def _is_wait_read_timeout(exc: requests.exceptions.ConnectionError) -> bool:
    """Whether `exc` is `container.wait(timeout=...)`'s read-timeout, wrapped.

    Discovered against a REAL Docker daemon (task 1.12), not inferred from
    docstrings: depending on the installed `requests`/`urllib3` versions, a
    `.wait(timeout=...)` deadline can surface as a bare
    `requests.exceptions.ReadTimeout` OR as `requests.exceptions.ConnectionError`
    wrapping the underlying `urllib3.exceptions.ReadTimeoutError` (docker-py's
    own docstring only documents the former). Genuine connectivity failures
    (daemon down, socket closed) also raise `ConnectionError` but do NOT wrap
    a `ReadTimeoutError` — this check tells the two apart so a real outage is
    never misclassified as a deterministic timeout (D5).
    """
    return any(isinstance(arg, urllib3.exceptions.ReadTimeoutError) for arg in exc.args)


def container_metric_outcome(*, timed_out: bool) -> str:
    """Map container completion to the finite metric outcome taxonomy."""
    return "timeout" if timed_out else "success"


class DockerContainerRunner(ContainerRunnerPort):
    """Sync `ContainerRunnerPort` adapter over the `docker` SDK (Module 6 D3).

    Container work is blocking I/O by nature (the SDK itself is sync) —
    callers MUST invoke `.run()` outside any asyncio event loop/DB session
    (see `workers/tasks/process_scan.py`).
    """

    def __init__(self, client: DockerClient | None = None) -> None:
        self._client = client if client is not None else docker.from_env()

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
        tmp_exec: bool = False,
    ) -> RunResult:
        """One `container.run` span covers this call's entire launch-to-exit
        lifetime — the deepest point of instrumentation for the scanning step
        (spec: "Span Coverage Stops at Container Launch/Exit"). Instrumentation
        NEVER reaches inside the launched container: no trace-context/env var
        is ever injected into `containers.run(...)`'s kwargs above, so no span
        or trace context can originate from the third-party scanner CLI
        process running inside it.
        """
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("container.run") as span:
            span.set_attribute("image", image)
            span.set_attribute("network_disabled", network_disabled)

            start = time.monotonic()
            container = self._client.containers.run(
                image=image,
                command=command,
                volumes={
                    volume_name: {"bind": mount_path, "mode": "ro" if read_only_mount else "rw"}
                },
                user=_NONROOT_USER,
                read_only=True,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                network_mode="none" if network_disabled else None,
                mem_limit=f"{limits.memory_mb}m",
                nano_cpus=limits.nano_cpus,
                pids_limit=limits.pids_limit,
                tmpfs={"/tmp": _TMPFS_MOUNT_OPTS_EXEC if tmp_exec else _TMPFS_MOUNT_OPTS},
                detach=True,
            )
            try:
                timed_out = False
                try:
                    wait_result = container.wait(timeout=timeout_seconds)
                    exit_code = int(wait_result["StatusCode"])
                except requests.exceptions.ReadTimeout:
                    timed_out = True
                    exit_code = -1
                    container.kill()
                except requests.exceptions.ConnectionError as exc:
                    if not _is_wait_read_timeout(exc):
                        raise
                    timed_out = True
                    exit_code = -1
                    container.kill()

                stdout = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")
                stderr = container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace")
            finally:
                container.remove(force=True)

            duration_ms = (time.monotonic() - start) * 1000
            span.set_attribute("exit_code", exit_code)
            span.set_attribute("timed_out", timed_out)
            span.set_attribute("duration_ms", duration_ms)
            from orchestrator.infrastructure.observability.metrics import record_container_duration

            record_container_duration(
                container_metric_outcome(timed_out=timed_out), duration_ms / 1000
            )

        return RunResult(exit_code=exit_code, stdout=stdout, stderr=stderr, timed_out=timed_out)
