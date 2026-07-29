"""`GitCheckout` — shallow-clone via a short-lived init-container over a named
Docker volume (Module 6 D2, tasks 1.9-1.11).

`FakeContainerRunner` drives the two-argv-run clone+rev-parse behavior
without a real Docker socket; a `MagicMock` stands in for the low-level
`docker` client (volume create/get/remove only — never invoked via
`ContainerRunnerPort`, so it needs its own double)."""

from __future__ import annotations

import io
import tarfile
from unittest.mock import MagicMock

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from orchestrator.domain.ports.container_runner_port import RunResult
from orchestrator.domain.value_objects.secret import Secret
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.vcs.git_checkout import CheckoutFailedError, GitCheckout
from tests.fakes.fake_container_runner import FakeContainerRunner

_CLONE_URL = "https://example.com/octocat/hello-world.git"
_REF = "main"


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql://x:x@localhost/x",
        redis_url="redis://localhost:6379/0",
        secret_key="s",
        jwt_secret_key="j",
    )


def test_checkout_runs_clone_then_rev_parse_as_two_argv_only_calls() -> None:
    fake_runner = FakeContainerRunner()
    fake_runner.script(
        RunResult(exit_code=0, stdout="", stderr="", timed_out=False),
        RunResult(exit_code=0, stdout="deadbeef1234\n", stderr="", timed_out=False),
    )
    docker_client = MagicMock()
    settings = _settings()
    checkout = GitCheckout(runner=fake_runner, docker_client=docker_client, settings=settings)

    ws = checkout.checkout(_CLONE_URL, _REF)

    assert len(fake_runner.calls) == 2
    clone_call, rev_parse_call = fake_runner.calls
    assert clone_call.command == [
        "clone",
        "--depth",
        "1",
        "--single-branch",
        "--branch",
        _REF,
        _CLONE_URL,
        "/workspace/checkout",
    ]
    assert clone_call.image == settings.scan_git_image
    assert clone_call.read_only_mount is False
    assert clone_call.network_disabled is False
    assert clone_call.mount_path == "/workspace"

    assert rev_parse_call.command == ["-C", "/workspace/checkout", "rev-parse", "HEAD"]
    assert rev_parse_call.image == settings.scan_git_image
    assert rev_parse_call.volume_name == clone_call.volume_name

    assert ws.head_sha == "deadbeef1234"


def test_checkout_creates_named_volume_before_running_containers() -> None:
    fake_runner = FakeContainerRunner()
    fake_runner.script(
        RunResult(exit_code=0, stdout="", stderr="", timed_out=False),
        RunResult(exit_code=0, stdout="abc\n", stderr="", timed_out=False),
    )
    docker_client = MagicMock()
    call_order: list[str] = []
    docker_client.volumes.create.side_effect = lambda **_: call_order.append("volume_create")
    docker_client.containers.run.side_effect = lambda **_: call_order.append("chmod_prep")
    original_run = fake_runner.run

    def _tracked_run(**kwargs: object) -> RunResult:
        call_order.append("container_run")
        return original_run(**kwargs)  # type: ignore[arg-type]

    fake_runner.run = _tracked_run  # type: ignore[method-assign]
    checkout = GitCheckout(runner=fake_runner, docker_client=docker_client, settings=_settings())

    ws = checkout.checkout(_CLONE_URL, _REF)

    docker_client.volumes.create.assert_called_once()
    created_name = docker_client.volumes.create.call_args.kwargs["name"]
    assert created_name.startswith("scan-")
    assert created_name == ws.volume_name
    assert call_order == ["volume_create", "chmod_prep", "container_run", "container_run"]


def test_checkout_chmods_the_fresh_volume_world_writable_before_the_nonroot_clone() -> None:
    """A freshly `docker.volumes.create()`d volume's mountpoint is root-owned
    on the host; without this world-writable prep step, the non-root
    (65532:65532) init-container the `ContainerRunnerPort` hardening
    contract mandates could never write its clone into it (discovered via
    the live-Docker proof, task 1.12 — not merely inferred from source)."""
    fake_runner = FakeContainerRunner()
    fake_runner.script(
        RunResult(exit_code=0, stdout="", stderr="", timed_out=False),
        RunResult(exit_code=0, stdout="abc\n", stderr="", timed_out=False),
    )
    docker_client = MagicMock()
    settings = _settings()
    checkout = GitCheckout(runner=fake_runner, docker_client=docker_client, settings=settings)

    ws = checkout.checkout(_CLONE_URL, _REF)

    docker_client.containers.run.assert_called_once()
    prep_kwargs = docker_client.containers.run.call_args.kwargs
    assert prep_kwargs["image"] == settings.scan_git_image
    assert prep_kwargs["entrypoint"] == "chmod"
    assert prep_kwargs["command"] == ["0777", "/workspace"]
    assert prep_kwargs["volumes"] == {ws.volume_name: {"bind": "/workspace", "mode": "rw"}}
    assert prep_kwargs["remove"] is True
    # Never on the untrusted-network path and never inheriting the hardened
    # nonroot user — it MUST run as root (default) to chmod a root-owned dir.
    assert prep_kwargs["network_mode"] == "none"
    assert "user" not in prep_kwargs


def test_checkout_raises_checkout_failed_error_on_nonzero_clone_exit() -> None:
    fake_runner = FakeContainerRunner()
    fake_runner.script(
        RunResult(
            exit_code=128,
            stdout="",
            stderr="fatal: Remote branch bad-ref not found",
            timed_out=False,
        )
    )
    docker_client = MagicMock()
    checkout = GitCheckout(runner=fake_runner, docker_client=docker_client, settings=_settings())

    with pytest.raises(CheckoutFailedError, match="clone"):
        checkout.checkout(_CLONE_URL, "bad-ref")

    assert len(fake_runner.calls) == 1  # rev-parse never attempted after a failed clone


def test_checkout_raises_checkout_failed_error_on_nonzero_rev_parse_exit() -> None:
    fake_runner = FakeContainerRunner()
    fake_runner.script(
        RunResult(exit_code=0, stdout="", stderr="", timed_out=False),
        RunResult(exit_code=128, stdout="", stderr="fatal: not a git repository", timed_out=False),
    )
    docker_client = MagicMock()
    checkout = GitCheckout(runner=fake_runner, docker_client=docker_client, settings=_settings())

    with pytest.raises(CheckoutFailedError, match="rev-parse"):
        checkout.checkout(_CLONE_URL, _REF)


def test_checkout_raises_credential_free_error_on_github_private_repo_when_none_configured() -> (
    None
):
    """Empirically confirmed live: `GIT_TERMINAL_PROMPT=0 git clone` against a
    private (or nonexistent — GitHub intentionally returns the identical
    message for both, for privacy) GitHub repo prints exactly this
    server-controlled `remote:` line, unlocalized, followed by a
    (client-locale-dependent) `fatal:` line. PR5 (task 5.9): when NO
    credential was supplied, the failure reason is
    "repository requires a credential; none is configured"."""
    fake_runner = FakeContainerRunner()
    fake_runner.script(
        RunResult(
            exit_code=128,
            stdout="",
            stderr=(
                "remote: Repository not found.\n"
                "fatal: repository 'https://github.com/octocat/private-repo.git/' not found\n"
            ),
            timed_out=False,
        )
    )
    docker_client = MagicMock()
    checkout = GitCheckout(runner=fake_runner, docker_client=docker_client, settings=_settings())

    with pytest.raises(
        CheckoutFailedError, match="repository requires a credential; none is configured"
    ):
        checkout.checkout("https://github.com/octocat/private-repo.git", _REF)

    assert len(fake_runner.calls) == 1  # rev-parse never attempted after a failed clone


def test_checkout_raises_credential_free_error_on_basic_auth_prompt_when_none_configured() -> None:
    """Empirically confirmed live: `GIT_TERMINAL_PROMPT=0 git clone` against a
    non-GitHub host requiring HTTP Basic auth (e.g. self-hosted Git/Bitbucket)
    prints exactly this message when no credentials are configured."""
    fake_runner = FakeContainerRunner()
    fake_runner.script(
        RunResult(
            exit_code=128,
            stdout="",
            stderr="fatal: could not read Username for 'https://bitbucket.org': "
            "terminal prompts disabled\n",
            timed_out=False,
        )
    )
    docker_client = MagicMock()
    checkout = GitCheckout(runner=fake_runner, docker_client=docker_client, settings=_settings())

    with pytest.raises(
        CheckoutFailedError, match="repository requires a credential; none is configured"
    ):
        checkout.checkout("https://bitbucket.org/private/repo.git", _REF)


def test_checkout_raises_credential_free_error_on_ssh_permission_denied_when_none_configured() -> (
    None
):
    """SSH remotes without a matching deploy key/agent key print this exact
    combo (well-documented git/OpenSSH convention: `Permission denied
    (publickey).` from ssh, followed by git's own access-rights hint)."""
    fake_runner = FakeContainerRunner()
    fake_runner.script(
        RunResult(
            exit_code=128,
            stdout="",
            stderr=(
                "git@github.com: Permission denied (publickey).\n"
                "fatal: Could not read from remote repository.\n\n"
                "Please make sure you have the correct access rights\n"
                "and the repository exists.\n"
            ),
            timed_out=False,
        )
    )
    docker_client = MagicMock()
    checkout = GitCheckout(runner=fake_runner, docker_client=docker_client, settings=_settings())

    with pytest.raises(
        CheckoutFailedError, match="repository requires a credential; none is configured"
    ):
        checkout.checkout("git@github.com:octocat/private-repo.git", _REF)


def test_checkout_auth_failure_with_credential_supplied_suggests_reentering_it() -> None:
    """PR5 (task 5.9): when a credential WAS supplied and the clone still
    looks like an auth failure (e.g. an expired/revoked token), the message
    steers the caller toward re-entering it — never the "none configured"
    wording, and never the token value itself."""
    fake_runner = FakeContainerRunner()
    fake_runner.script(
        RunResult(
            exit_code=128,
            stdout="",
            stderr="remote: Repository not found.\nfatal: repository not found\n",
            timed_out=False,
        )
    )
    docker_client = MagicMock()
    checkout = GitCheckout(runner=fake_runner, docker_client=docker_client, settings=_settings())
    token = "ghp_expired-or-revoked-token"

    with pytest.raises(CheckoutFailedError, match="re-enter the stored credential") as excinfo:
        checkout.checkout(
            "https://github.com/octocat/private-repo.git", _REF, credential=Secret(token)
        )

    assert token not in str(excinfo.value)
    assert "none is configured" not in str(excinfo.value)


def test_checkout_generic_bad_ref_message_unaffected_by_auth_detection() -> None:
    """Regression guard: a plain bad-ref failure (no auth-failure markers)
    MUST keep the existing generic "clone failed" message, not be
    misclassified as a credential-resolution failure."""
    fake_runner = FakeContainerRunner()
    fake_runner.script(
        RunResult(
            exit_code=128,
            stdout="",
            stderr="fatal: Remote branch bad-ref not found",
            timed_out=False,
        )
    )
    docker_client = MagicMock()
    checkout = GitCheckout(runner=fake_runner, docker_client=docker_client, settings=_settings())

    with pytest.raises(CheckoutFailedError, match="clone"):
        checkout.checkout(_CLONE_URL, "bad-ref")


def test_checkout_removes_volume_when_clone_fails() -> None:
    fake_runner = FakeContainerRunner()
    fake_runner.script(
        RunResult(exit_code=128, stdout="", stderr="fatal: bad ref", timed_out=False)
    )
    docker_client = MagicMock()
    checkout = GitCheckout(runner=fake_runner, docker_client=docker_client, settings=_settings())

    with pytest.raises(CheckoutFailedError):
        checkout.checkout(_CLONE_URL, "bad-ref")

    created_name = docker_client.volumes.create.call_args.kwargs["name"]
    docker_client.volumes.get.assert_called_once_with(created_name)
    docker_client.volumes.get.return_value.remove.assert_called_once_with(force=True)


def test_checkout_removes_volume_and_reraises_when_runner_raises_unexpectedly() -> None:
    fake_runner = FakeContainerRunner()

    def _raise(**_: object) -> RunResult:
        raise RuntimeError("docker daemon unreachable")

    fake_runner.run = _raise  # type: ignore[method-assign]
    docker_client = MagicMock()
    checkout = GitCheckout(runner=fake_runner, docker_client=docker_client, settings=_settings())

    with pytest.raises(RuntimeError, match="docker daemon unreachable"):
        checkout.checkout(_CLONE_URL, _REF)

    docker_client.volumes.get.return_value.remove.assert_called_once_with(force=True)


def test_checkout_emits_a_git_checkout_span_wrapping_clone_and_rev_parse(
    span_exporter: InMemorySpanExporter,
) -> None:
    fake_runner = FakeContainerRunner()
    fake_runner.script(
        RunResult(exit_code=0, stdout="", stderr="", timed_out=False),
        RunResult(exit_code=0, stdout="deadbeef1234\n", stderr="", timed_out=False),
    )
    docker_client = MagicMock()
    checkout = GitCheckout(runner=fake_runner, docker_client=docker_client, settings=_settings())

    checkout.checkout(_CLONE_URL, _REF)

    spans = span_exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "git.checkout"
    # Threat matrix: never carry clone_url/ref as attributes (either may
    # embed a credential or a secret branch name).
    assert not (span.attributes or {})


def test_checkout_emits_a_git_checkout_span_even_on_clone_failure(
    span_exporter: InMemorySpanExporter,
) -> None:
    fake_runner = FakeContainerRunner()
    fake_runner.script(
        RunResult(exit_code=128, stdout="", stderr="fatal: bad ref", timed_out=False)
    )
    docker_client = MagicMock()
    checkout = GitCheckout(runner=fake_runner, docker_client=docker_client, settings=_settings())

    with pytest.raises(CheckoutFailedError):
        checkout.checkout(_CLONE_URL, "bad-ref")

    spans = span_exporter.get_finished_spans()
    assert [span.name for span in spans] == ["git.checkout"]


def test_workspace_context_manager_removes_volume_on_exit() -> None:
    fake_runner = FakeContainerRunner()
    fake_runner.script(
        RunResult(exit_code=0, stdout="", stderr="", timed_out=False),
        RunResult(exit_code=0, stdout="sha\n", stderr="", timed_out=False),
    )
    docker_client = MagicMock()
    checkout = GitCheckout(runner=fake_runner, docker_client=docker_client, settings=_settings())
    ws = checkout.checkout(_CLONE_URL, _REF)
    docker_client.volumes.get.reset_mock()  # only the deferred exit-time removal should count here

    with ws as entered:
        assert entered is ws

    docker_client.volumes.get.assert_called_once_with(ws.volume_name)
    docker_client.volumes.get.return_value.remove.assert_called_once_with(force=True)


# --- PR5: credential-authenticated checkout ---------------------------------

_PRIVATE_URL = "https://github.com/octocat/private-repo.git"


def _scripted_success(fake_runner: FakeContainerRunner) -> None:
    fake_runner.script(
        RunResult(exit_code=0, stdout="", stderr="", timed_out=False),
        RunResult(exit_code=0, stdout="deadbeef1234\n", stderr="", timed_out=False),
    )


def test_checkout_without_credential_never_writes_or_shreds_credential_files() -> None:
    """Regression: `credential=None` must reproduce today's public-repo
    behavior byte-for-byte — no `containers.create` (credential write) and
    no `entrypoint="rm"` (shred) call at all."""
    fake_runner = FakeContainerRunner()
    _scripted_success(fake_runner)
    docker_client = MagicMock()
    checkout = GitCheckout(runner=fake_runner, docker_client=docker_client, settings=_settings())

    checkout.checkout(_CLONE_URL, _REF)

    docker_client.containers.create.assert_not_called()
    rm_calls = [
        call
        for call in docker_client.containers.run.call_args_list
        if call.kwargs.get("entrypoint") == "rm"
    ]
    assert rm_calls == []
    clone_call = fake_runner.calls[0]
    assert clone_call.env is None


def test_checkout_with_credential_writes_gitconfig_and_git_credentials_before_clone() -> None:
    fake_runner = FakeContainerRunner()
    _scripted_success(fake_runner)
    docker_client = MagicMock()
    created_container = MagicMock()
    docker_client.containers.create.return_value = created_container
    checkout = GitCheckout(runner=fake_runner, docker_client=docker_client, settings=_settings())

    checkout.checkout(_PRIVATE_URL, _REF, credential=Secret("ghp_super-secret-token"))

    docker_client.containers.create.assert_called_once()
    created_container.put_archive.assert_called_once()
    dest_path, archive_bytes = created_container.put_archive.call_args.args
    assert dest_path == "/workspace"
    created_container.remove.assert_called_once_with(force=True)

    with tarfile.open(fileobj=io.BytesIO(archive_bytes)) as archive:
        names = {member.name: member for member in archive.getmembers()}
        assert names[".git-credentials"].mode == 0o600
        credentials = archive.extractfile(".git-credentials")
        assert credentials is not None
        assert (
            credentials.read().decode()
            == "https://x-access-token:ghp_super-secret-token@github.com\n"
        )
        gitconfig = archive.extractfile(".gitconfig")
        assert gitconfig is not None
        gitconfig_contents = gitconfig.read().decode()
        assert "[credential]" in gitconfig_contents
        assert "helper = store --file=/workspace/.git-credentials" in gitconfig_contents

    # Written strictly before the clone call.
    clone_call = fake_runner.calls[0]
    assert clone_call.command[:2] == ["clone", "--depth"]


def test_checkout_with_credential_passes_env_to_clone_call_only_and_never_touches_argv() -> None:
    fake_runner = FakeContainerRunner()
    _scripted_success(fake_runner)
    docker_client = MagicMock()
    checkout = GitCheckout(runner=fake_runner, docker_client=docker_client, settings=_settings())
    token = "ghp_super-secret-token"

    checkout.checkout(_PRIVATE_URL, _REF, credential=Secret(token))

    clone_call, rev_parse_call = fake_runner.calls
    assert clone_call.env == {"HOME": "/workspace", "GIT_TERMINAL_PROMPT": "0"}
    assert rev_parse_call.env is None
    assert token not in " ".join(clone_call.command)
    assert token not in clone_call.command[clone_call.command.index(_PRIVATE_URL)]
    assert _PRIVATE_URL in clone_call.command  # clone_url argv stays byte-for-byte unchanged


def test_checkout_with_credential_shreds_files_before_returning_workspace() -> None:
    fake_runner = FakeContainerRunner()
    _scripted_success(fake_runner)
    docker_client = MagicMock()
    call_order: list[str] = []
    docker_client.containers.run.side_effect = lambda **kwargs: call_order.append(
        "shred" if kwargs.get("entrypoint") == "rm" else "chmod_prep"
    )
    original_run = fake_runner.run

    def _tracked_run(**kwargs: object) -> RunResult:
        call_order.append("clone_or_rev_parse")
        return original_run(**kwargs)  # type: ignore[arg-type]

    fake_runner.run = _tracked_run  # type: ignore[method-assign]
    checkout = GitCheckout(runner=fake_runner, docker_client=docker_client, settings=_settings())

    ws = checkout.checkout(_PRIVATE_URL, _REF, credential=Secret("ghp_token"))

    assert call_order == [
        "chmod_prep",
        "clone_or_rev_parse",
        "clone_or_rev_parse",
        "shred",
    ]
    assert ws.head_sha == "deadbeef1234"
    shred_kwargs = [
        call.kwargs
        for call in docker_client.containers.run.call_args_list
        if call.kwargs.get("entrypoint") == "rm"
    ][0]
    assert shred_kwargs["command"] == ["-f", "/workspace/.git-credentials", "/workspace/.gitconfig"]


def test_checkout_shred_failure_raises_checkout_failed_error_no_workspace_returned() -> None:
    """Fail-closed (task 5.7/5.8): if the shred step itself raises, no
    `Workspace` is ever returned — a scanner must never get a chance to
    mount a volume that could still hold a credential file."""
    fake_runner = FakeContainerRunner()
    _scripted_success(fake_runner)
    docker_client = MagicMock()

    def _run_side_effect(**kwargs: object) -> object:
        if kwargs.get("entrypoint") == "rm":
            raise RuntimeError("simulated shred failure")
        return MagicMock()

    docker_client.containers.run.side_effect = _run_side_effect
    checkout = GitCheckout(runner=fake_runner, docker_client=docker_client, settings=_settings())

    with pytest.raises(CheckoutFailedError, match="shred"):
        checkout.checkout(_PRIVATE_URL, _REF, credential=Secret("ghp_token"))

    # Fail-closed cleanup: the volume backing the (never-returned) workspace
    # is force-removed, same as any other checkout failure.
    docker_client.volumes.get.return_value.remove.assert_called_with(force=True)


def test_credential_file_hardcodes_github_host_never_derived_from_clone_url() -> None:
    """Threat matrix (git repository selection): the stored
    git-credential-store entry is keyed to a HARDCODED `github.com` host,
    never parsed from `clone_url` — so it can never be presented to any
    other remote regardless of what host a crafted `clone_url` claims
    (git's own credential store matches strictly by scheme+host)."""
    fake_runner = FakeContainerRunner()
    _scripted_success(fake_runner)
    docker_client = MagicMock()
    created_container = MagicMock()
    docker_client.containers.create.return_value = created_container
    checkout = GitCheckout(runner=fake_runner, docker_client=docker_client, settings=_settings())

    checkout.checkout(
        "https://not-github.example.com/acme/private.git",
        _REF,
        credential=Secret("ghp_token"),
    )

    _, archive_bytes = created_container.put_archive.call_args.args
    with tarfile.open(fileobj=io.BytesIO(archive_bytes)) as archive:
        credentials = archive.extractfile(".git-credentials")
        assert credentials is not None
        assert credentials.read().decode().endswith("@github.com\n")


def test_ref_with_path_traversal_or_leading_dash_cannot_escape_the_fixed_checkout_dir() -> None:
    """Threat matrix (git repository selection): `_CHECKOUT_DIR` is a
    hardcoded module constant, never derived from `ref` — a crafted `ref`
    (path traversal, leading `-`) has nothing of its own to escape with;
    the clone destination stays fixed regardless of `ref`'s content."""
    for malicious_ref in ("../../../etc/passwd", "-rm-rf", "--upload-pack=evil"):
        fake_runner = FakeContainerRunner()
        _scripted_success(fake_runner)
        docker_client = MagicMock()
        checkout = GitCheckout(
            runner=fake_runner, docker_client=docker_client, settings=_settings()
        )

        checkout.checkout(_CLONE_URL, malicious_ref)

        clone_call = fake_runner.calls[0]
        assert clone_call.command[-1] == "/workspace/checkout"
        assert clone_call.command[-2] == _CLONE_URL
        assert clone_call.command[clone_call.command.index("--branch") + 1] == malicious_ref
