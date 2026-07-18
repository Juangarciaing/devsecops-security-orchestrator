"""`GitCheckout` — shallow-clone a repo into a per-checkout named Docker
volume via a short-lived `alpine/git` init-container (Module 6 D2).

The worker never runs `git` itself and needs no local checkout mount: a
throwaway init-container mounts the (rw) volume, clones, and resolves the
real `HEAD` SHA via two SEPARATE argv-only runs — never a shell string —
which closes the shell-injection surface a crafted `ref`/`clone_url` would
otherwise open. `Workspace.volume_name` is later mounted read-only by the
scanner container (PR2/PR3), which is why the volume is NOT removed at the
end of `.checkout()` on success — only `Workspace.__exit__` (the caller's
`with` block, entered AFTER the scan has read from it) removes it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from types import TracebackType
from typing import TYPE_CHECKING

from orchestrator.domain.ports.container_runner_port import ContainerRunnerPort, ResourceLimits

if TYPE_CHECKING:
    from docker import DockerClient

    from orchestrator.infrastructure.config.settings import Settings

_WORKSPACE_MOUNT_PATH = "/workspace"
_CHECKOUT_DIR = "/workspace/checkout"

#: Module 6 is public-repos-only (non-goal: no credential resolution, spec's
#: "Module 6 Non-Goals"). These substrings (case-insensitive) identify a
#: clone `stderr` as an authentication-required failure rather than a
#: generic bad-ref/network error, so the spec's "Private repo" scenario can
#: surface its specific literal reason. Empirically confirmed via live
#: `GIT_TERMINAL_PROMPT=0 git clone` runs (not merely inferred from docs):
#: - GitHub returns "remote: Repository not found." (server-controlled,
#:   unlocalized) for BOTH nonexistent AND private repos alike — GitHub
#:   deliberately never distinguishes the two, for privacy.
#: - Non-GitHub HTTP(S) remotes needing Basic auth (Bitbucket, self-hosted
#:   Git/GitLab, ...) print "could not read Username for '<url>': terminal
#:   prompts disabled" when no credentials are configured non-interactively.
#: - SSH remotes without a matching key print OpenSSH's "Permission denied
#:   (publickey)." followed by git's own access-rights hint — a
#:   well-documented git/OpenSSH convention.
_AUTH_FAILURE_MARKERS: tuple[str, ...] = (
    "repository not found",
    "could not read username",
    "could not read password",
    "authentication failed",
    "permission denied (publickey)",
    "please make sure you have the correct access rights",
)

_CREDENTIAL_RESOLUTION_NOT_IMPLEMENTED = "credential resolution not yet implemented"


def _looks_like_auth_failure(stderr: str) -> bool:
    lowered = stderr.lower()
    return any(marker in lowered for marker in _AUTH_FAILURE_MARKERS)


class CheckoutFailedError(Exception):
    """Deterministic checkout failure (bad ref, private repo, ...) — never retried (D5)."""


@dataclass(slots=True)
class Workspace:
    """A resolved checkout: the named volume holding it plus the real HEAD SHA.

    A context manager whose `__exit__` force-removes the backing volume —
    callers `with` this AFTER they are done reading from `volume_name` (see
    module docstring for why cleanup is deferred, not immediate)."""

    volume_name: str
    head_sha: str
    _docker_client: DockerClient = field(repr=False)

    def __enter__(self) -> Workspace:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._docker_client.volumes.get(self.volume_name).remove(force=True)


class GitCheckout:
    """Orchestrates the named-volume + init-container checkout handoff (D1, D2)."""

    def __init__(
        self, runner: ContainerRunnerPort, docker_client: DockerClient, settings: Settings
    ) -> None:
        self._runner = runner
        self._docker_client = docker_client
        self._settings = settings

    def checkout(self, clone_url: str, ref: str) -> Workspace:
        """Shallow-clone `clone_url` at `ref` and resolve its real HEAD SHA.

        Raises `CheckoutFailedError` (no retry) on a non-zero clone/rev-parse
        exit. On ANY failure — a non-zero exit or the run itself raising —
        the volume created for this attempt is force-removed before the
        error propagates; the ORIGINAL exception type is re-raised
        unchanged so transient Docker-daemon errors stay distinguishable
        from deterministic checkout failures (D5).
        """
        volume_name = f"scan-{uuid.uuid4().hex}"
        self._docker_client.volumes.create(name=volume_name)

        try:
            self._prepare_volume_permissions(volume_name)
            limits = self._resource_limits()

            clone_result = self._runner.run(
                image=self._settings.scan_git_image,
                command=[
                    "clone",
                    "--depth",
                    "1",
                    "--single-branch",
                    "--branch",
                    ref,
                    clone_url,
                    _CHECKOUT_DIR,
                ],
                volume_name=volume_name,
                mount_path=_WORKSPACE_MOUNT_PATH,
                read_only_mount=False,
                network_disabled=False,
                limits=limits,
                timeout_seconds=self._settings.scan_timeout_seconds,
            )
            if clone_result.exit_code != 0:
                if _looks_like_auth_failure(clone_result.stderr):
                    raise CheckoutFailedError(_CREDENTIAL_RESOLUTION_NOT_IMPLEMENTED)
                raise CheckoutFailedError(
                    f"git clone failed (exit {clone_result.exit_code}): {clone_result.stderr}"
                )

            rev_parse_result = self._runner.run(
                image=self._settings.scan_git_image,
                command=["-C", _CHECKOUT_DIR, "rev-parse", "HEAD"],
                volume_name=volume_name,
                mount_path=_WORKSPACE_MOUNT_PATH,
                read_only_mount=False,
                network_disabled=False,
                limits=limits,
                timeout_seconds=self._settings.scan_timeout_seconds,
            )
            if rev_parse_result.exit_code != 0:
                raise CheckoutFailedError(
                    f"git rev-parse HEAD failed (exit {rev_parse_result.exit_code}): "
                    f"{rev_parse_result.stderr}"
                )

            head_sha = rev_parse_result.stdout.strip()
        except Exception:
            self._docker_client.volumes.get(volume_name).remove(force=True)
            raise

        return Workspace(
            volume_name=volume_name, head_sha=head_sha, _docker_client=self._docker_client
        )

    def _prepare_volume_permissions(self, volume_name: str) -> None:
        """`chmod 0777` the freshly created (root-owned) volume mountpoint.

        Discovered live (task 1.12), not inferred from source: the local
        Docker volume driver creates a NEW volume's mountpoint owned by
        root:root on the host. `ContainerRunnerPort.run()` unconditionally
        launches every container as the hardened non-root
        `65532:65532` user (D-invariant, never relaxed) — without this
        one-off prep step, that non-root init-container could never write
        its clone into a brand-new volume at all (`Permission denied`).

        This step runs OUTSIDE `ContainerRunnerPort` (it genuinely needs
        root to chmod a root-owned directory) but stays narrowly scoped and
        low-risk: an argv-only, hardcoded (never attacker-influenced)
        command, no network, against a volume that holds ZERO untrusted
        content yet (this runs strictly before the clone).
        """
        self._docker_client.containers.run(
            image=self._settings.scan_git_image,
            entrypoint="chmod",
            command=["0777", _WORKSPACE_MOUNT_PATH],
            volumes={volume_name: {"bind": _WORKSPACE_MOUNT_PATH, "mode": "rw"}},
            network_mode="none",
            remove=True,
        )

    def _resource_limits(self) -> ResourceLimits:
        return ResourceLimits(
            memory_mb=self._settings.scan_memory_limit_mb,
            nano_cpus=int(self._settings.scan_cpu_limit * 1_000_000_000),
            pids_limit=self._settings.scan_pids_limit,
        )
