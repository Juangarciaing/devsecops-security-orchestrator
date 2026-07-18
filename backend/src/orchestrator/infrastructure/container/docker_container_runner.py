"""`DockerContainerRunner` — `docker` Python SDK implementation of `ContainerRunnerPort`.

One `.run()` call launches exactly one hardened, ephemeral container against
a pre-existing named Docker volume, blocks until it exits or the wall-clock
timeout elapses, and force-removes it before returning — success, failure,
or timeout (Module 6 spec: "Wall-Clock Timeout Enforcement", "Hardened
Ephemeral Container Execution").
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import docker
import requests.exceptions
import urllib3.exceptions

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
    ) -> RunResult:
        container = self._client.containers.run(
            image=image,
            command=command,
            volumes={volume_name: {"bind": mount_path, "mode": "ro" if read_only_mount else "rw"}},
            user=_NONROOT_USER,
            read_only=True,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            network_mode="none" if network_disabled else None,
            mem_limit=f"{limits.memory_mb}m",
            nano_cpus=limits.nano_cpus,
            pids_limit=limits.pids_limit,
            tmpfs={"/tmp": _TMPFS_MOUNT_OPTS},
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

        return RunResult(exit_code=exit_code, stdout=stdout, stderr=stderr, timed_out=timed_out)
