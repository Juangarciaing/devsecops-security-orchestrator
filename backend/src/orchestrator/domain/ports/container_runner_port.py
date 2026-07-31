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


@dataclass(frozen=True, slots=True)
class TmpfsMount:
    """One `extra_tmpfs` entry (dast-scanner PR5b).

    Replaces the original bare-path-string shape shipped in PR4 (which had
    zero real callers — only a test exercised it, mirroring a rung-2
    fallback the PR4 spike went on to prove insufficient): a bare path
    cannot express per-mount uid/gid/size options, and ZAP's `/home/zap`
    genuinely needs `uid=1000,gid=1000,size>=512m` (PR4 spike, design D6
    rung 3) — undersizing it to this port's existing 64m default silently
    corrupts ZAP's config mid-write.

    `uid`/`gid`/`size_mb` all default to `None`, which reproduces a bare
    path's previous behavior byte-for-byte (implementation-default mount
    options, no explicit owner).
    """

    path: str
    uid: int | None = None
    gid: int | None = None
    size_mb: int | None = None


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
        tmp_exec: bool = False,
        cleanup_anonymous_volumes: bool = False,
        env: dict[str, str] | None = None,
        network_name: str | None = None,
        extra_tmpfs: tuple[TmpfsMount, ...] = (),
        user: str | None = None,
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

        `tmp_exec` (Module 11 D7b, opt-in, default `False`): whether the
        ephemeral `/tmp` (a tmpfs) permits executing files from it. Defaults
        to the strict `noexec` posture every caller relied on before this
        flag existed (Gitleaks, `GitCheckout`) — a caller must explicitly
        pass `tmp_exec=True` to relax it. Discovered live-Docker necessity:
        pip-audit bootstraps an internal audit virtualenv under `/tmp` and
        cannot function under `noexec` (upstream limitation,
        pypa/pip-audit#732) — no other scanner needs this, so it is scoped
        as a narrow per-call opt-in rather than a global relaxation.

        `env` (PR4, appended-and-defaulted, additive — no existing caller
        needs to change): non-secret environment variables ONLY (e.g.
        `HOME`, `GIT_TERMINAL_PROMPT`). Docker exposes a container's
        environment via `docker inspect` / `Config.Env` — implementations
        and callers MUST NOT place a plaintext credential or secret value
        here. Implementations MUST NOT emit `env` keys or values as OTel
        span attributes, Prometheus metric labels, or log fields. When
        `env` is `None` (the default), behavior MUST be byte-for-byte
        identical to calling `.run()` without this parameter at all.

        `network_name` (PR4, appended-and-defaulted): join the container to
        this pre-existing Docker network by name instead of the implicit
        default bridge. `None` (the default) MUST reproduce today's
        behavior byte-for-byte. Implementations MUST raise `ValueError` if
        `network_disabled=True` is combined with a non-`None`
        `network_name` — the two are mutually exclusive by construction
        (fail closed rather than silently pick one).

        `extra_tmpfs` (PR4, reshaped by dast-scanner PR5b to `tuple[TmpfsMount,
        ...]`): additional writable tmpfs mounts beyond `/tmp`, merged into
        whatever tmpfs mechanism the runner already uses. Empty (the
        default) changes nothing for any existing caller. Each `TmpfsMount`
        may carry `uid`/`gid`/`size_mb` mount options; all `None` reproduces
        this port's existing implementation-default tmpfs options.

        `user` (dast-scanner PR5b, design D6 rung 3, appended-and-defaulted):
        overrides this port's hardened non-root uid:gid for THIS call only.
        `None` (the default) MUST reproduce today's behavior byte-for-byte —
        implementations still launch as their existing default non-root
        user. This is a narrow per-call opt-in (mirrors `tmp_exec`'s shape
        exactly) for the one scanner proven to need it live (ZAP resolves
        its home directory via native `getpwuid()` and ignores `$HOME`) —
        never a global relaxation, and never permitted to select root.
        """
