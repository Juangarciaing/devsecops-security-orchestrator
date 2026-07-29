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

PR5 (secrets-manager D4): an optional `credential: Secret | None` streams a
git-credential-store file pair into the SAME volume, over the Docker API
(`put_archive` on a created-but-never-started container — never argv, never
`Config.Env`), strictly before the clone runs, and shreds both files before
`.checkout()` ever returns a `Workspace` to a caller that might mount the
volume into a scanner container.
"""

from __future__ import annotations

import io
import tarfile
import uuid
from dataclasses import dataclass, field
from types import TracebackType
from typing import TYPE_CHECKING, Any

from opentelemetry import trace

from orchestrator.domain.ports.container_runner_port import ContainerRunnerPort, ResourceLimits

if TYPE_CHECKING:
    from docker import DockerClient

    from orchestrator.domain.value_objects.secret import Secret
    from orchestrator.infrastructure.config.settings import Settings

_WORKSPACE_MOUNT_PATH = "/workspace"
_CHECKOUT_DIR = "/workspace/checkout"

#: Matches `DockerContainerRunner`'s hardened non-root UID:GID
#: (`_NONROOT_USER = "65532:65532"`) — every clone/scan container this
#: system launches runs as this UID, so a credential file written as root
#: (put_archive's default tar ownership) would be unreadable to it. Kept as
#: a small local duplicate rather than a cross-module import of a private
#: name; if the hardened UID ever changes, both constants must move together.
_NONROOT_UID = 65532
_NONROOT_GID = 65532

#: PR5 (D4): the credential is delivered as a standard git-credential-store
#: file pair, keyed to a HARDCODED host — never derived from `clone_url` —
#: so the stored entry can never be presented to any other remote
#: regardless of what host a crafted `clone_url` claims (git's own
#: credential store matches strictly by scheme+host).
_CREDENTIAL_HOST = "github.com"
_CREDENTIAL_USERNAME = "x-access-token"
_GIT_CREDENTIALS_FILE = f"{_WORKSPACE_MOUNT_PATH}/.git-credentials"
_GITCONFIG_FILE = f"{_WORKSPACE_MOUNT_PATH}/.gitconfig"

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


def _looks_like_auth_failure(stderr: str) -> bool:
    lowered = stderr.lower()
    return any(marker in lowered for marker in _AUTH_FAILURE_MARKERS)


def _auth_failure_message(credential: Secret | None) -> str:
    """PR5 (task 5.9): branch the auth-failure reason on whether a stored
    credential was actually supplied to this attempt."""
    if credential is not None:
        return "authentication failed; re-enter the stored credential"
    return "repository requires a credential; none is configured"


def _build_credential_archive(*, gitconfig_contents: str, credentials_contents: str) -> bytes:
    """Build an in-memory tar with `.gitconfig` (0644) and `.git-credentials`
    (0600), both owned by the hardened non-root clone UID — `put_archive`
    extracts with whatever uid/gid/mode a tar header carries, so without
    this the non-root clone container could never read either file back."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        _add_tar_entry(archive, ".gitconfig", gitconfig_contents, mode=0o644)
        _add_tar_entry(archive, ".git-credentials", credentials_contents, mode=0o600)
    return buffer.getvalue()


def _add_tar_entry(archive: tarfile.TarFile, name: str, contents: str, *, mode: int) -> None:
    data = contents.encode("utf-8")
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    info.mode = mode
    info.uid = _NONROOT_UID
    info.gid = _NONROOT_GID
    archive.addfile(info, io.BytesIO(data))


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
        self,
        runner: ContainerRunnerPort,
        docker_client: DockerClient,
        settings: Settings,
        *,
        cleanup_anonymous_volumes: bool = False,
    ) -> None:
        self._runner = runner
        self._docker_client = docker_client
        self._settings = settings
        self._cleanup_anonymous_volumes = cleanup_anonymous_volumes

    def checkout(self, clone_url: str, ref: str, credential: Secret | None = None) -> Workspace:
        """Shallow-clone `clone_url` at `ref` and resolve its real HEAD SHA.

        `credential=None` (default) reproduces today's public-repo behavior
        byte-for-byte. When a `credential` IS supplied (PR5, design D4): a
        git-credential-store file pair is streamed into the volume via
        `put_archive` on a created-but-never-started container BEFORE the
        clone runs; the clone's `runner.run()` call (only) then receives
        `env={"HOME": ..., "GIT_TERMINAL_PROMPT": "0"}` — a path and a flag,
        never the secret itself. Both credential files are shredded before
        this method ever returns a `Workspace` — if the shred step itself
        fails, `CheckoutFailedError` is raised and NO `Workspace` is
        returned (fail-closed: no scanner ever gets a chance to mount a
        volume that could still hold a credential file).

        Raises `CheckoutFailedError` (no retry) on a non-zero clone/rev-parse
        exit, or on a shred failure. On ANY clone/rev-parse failure — a
        non-zero exit or the run itself raising — the volume created for
        this attempt is force-removed before the error propagates; the
        ORIGINAL exception type is re-raised unchanged so transient
        Docker-daemon errors stay distinguishable from deterministic
        checkout failures (D5).

        Module 13a: one `git.checkout` span wraps clone + rev-parse. Never
        carries `clone_url`/`ref` as attributes (threat matrix: either may
        embed a credential or a secret branch name).
        """
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("git.checkout"):
            volume_name = f"scan-{uuid.uuid4().hex}"
            self._docker_client.volumes.create(name=volume_name)

            try:
                self._prepare_volume_permissions(volume_name)
                limits = self._resource_limits()

                clone_env: dict[str, str] | None = None
                if credential is not None:
                    self._write_credential_files(volume_name, credential)
                    clone_env = {
                        "HOME": _WORKSPACE_MOUNT_PATH,
                        "GIT_TERMINAL_PROMPT": "0",
                    }

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
                    cleanup_anonymous_volumes=self._cleanup_anonymous_volumes,
                    env=clone_env,
                )
                if clone_result.exit_code != 0:
                    if _looks_like_auth_failure(clone_result.stderr):
                        raise CheckoutFailedError(_auth_failure_message(credential))
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
                    cleanup_anonymous_volumes=self._cleanup_anonymous_volumes,
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

            if credential is not None:
                try:
                    self._shred_credential_files(volume_name)
                except Exception as exc:
                    self._docker_client.volumes.get(volume_name).remove(force=True)
                    raise CheckoutFailedError(
                        "failed to shred credential files before returning workspace"
                    ) from exc

        return Workspace(
            volume_name=volume_name, head_sha=head_sha, _docker_client=self._docker_client
        )

    def _write_credential_files(self, volume_name: str, credential: Secret) -> None:
        """Stream `.gitconfig` + `.git-credentials` into the shared checkout
        volume via a created-but-never-started container's `put_archive`
        (D4, confirmed viable against a real Docker daemon by PR4's spike):
        the credential value never touches argv or `Config.Env`."""
        credentials_contents = (
            f"https://{_CREDENTIAL_USERNAME}:{credential.reveal()}@{_CREDENTIAL_HOST}\n"
        )
        gitconfig_contents = f"[credential]\n\thelper = store --file={_GIT_CREDENTIALS_FILE}\n"
        archive = _build_credential_archive(
            gitconfig_contents=gitconfig_contents, credentials_contents=credentials_contents
        )

        container = self._docker_client.containers.create(
            image=self._settings.scan_git_image,
            volumes={volume_name: {"bind": _WORKSPACE_MOUNT_PATH, "mode": "rw"}},
            network_mode="none",
        )
        try:
            container.put_archive(_WORKSPACE_MOUNT_PATH, archive)
        finally:
            container.remove(force=True)

    def _shred_credential_files(self, volume_name: str) -> None:
        """`rm -f` both credential files before `.checkout()` ever returns a
        `Workspace` — mirrors `_prepare_volume_permissions`'s
        entrypoint-override shape. Any exception raised here is converted by
        the caller into `CheckoutFailedError`: fail-closed, no `Workspace`
        is ever handed back while a credential file could still be on the
        volume a scanner is about to mount."""
        run_kwargs: dict[str, Any] = {
            "image": self._settings.scan_git_image,
            "entrypoint": "rm",
            "command": ["-f", _GIT_CREDENTIALS_FILE, _GITCONFIG_FILE],
            "volumes": {volume_name: {"bind": _WORKSPACE_MOUNT_PATH, "mode": "rw"}},
            "network_mode": "none",
        }
        if self._cleanup_anonymous_volumes:
            container = self._docker_client.containers.run(**run_kwargs, detach=True)
            try:
                container.wait()
            finally:
                container.remove(force=True, v=True)
        else:
            self._docker_client.containers.run(**run_kwargs, remove=True)

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
        run_kwargs: dict[str, Any] = {
            "image": self._settings.scan_git_image,
            "entrypoint": "chmod",
            "command": ["0777", _WORKSPACE_MOUNT_PATH],
            "volumes": {volume_name: {"bind": _WORKSPACE_MOUNT_PATH, "mode": "rw"}},
            "network_mode": "none",
        }
        if self._cleanup_anonymous_volumes:
            container = self._docker_client.containers.run(**run_kwargs, detach=True)
            try:
                container.wait()
            finally:
                container.remove(force=True, v=True)
        else:
            self._docker_client.containers.run(**run_kwargs, remove=True)

    def _resource_limits(self) -> ResourceLimits:
        return ResourceLimits(
            memory_mb=self._settings.scan_memory_limit_mb,
            nano_cpus=int(self._settings.scan_cpu_limit * 1_000_000_000),
            pids_limit=self._settings.scan_pids_limit,
        )
