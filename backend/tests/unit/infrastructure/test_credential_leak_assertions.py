"""Aggregate leak-assertion suite (PR5, tasks 5.15/5.16) — the single most
security-critical proof in this slice.

Wires a real `GitCheckout` + `GitleaksDockerExecution` against a
`FakeContainerRunner` and an instrumented `docker_client` double, and proves,
end to end, over one full checkout-then-scan cycle with a real credential:

- no `FakeContainerRunner.RecordedRun` anywhere (clone, rev-parse, OR the
  scanner invocation) ever carries the raw token in its `command` or `env`
- the SCANNER container's `RecordedRun.env` is always `None` (the scanner
  never receives the credential — only the checkout step does)
- the shred step (a real `docker_client.containers.run(entrypoint="rm", ...)`
  call) happens strictly BEFORE the scanner's `RecordedRun` even exists,
  proven via one shared, ordered event log both fakes append to
- the token never appears in any Docker SDK call's `command`/`environment`
  kwargs anywhere on the `docker_client` double either (the credential
  ONLY ever travels inside the `put_archive` tar payload)
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from orchestrator.domain.ports.container_runner_port import RunResult
from orchestrator.domain.value_objects.enums import ScannerType
from orchestrator.domain.value_objects.secret import Secret
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.container.gitleaks_docker_execution import GitleaksDockerExecution
from tests.fakes.fake_container_runner import FakeContainerRunner

_TOKEN = "ghp_leak-assertion-canary-token"  # noqa: S105 — test fixture only, never a real secret
_PRIVATE_URL = "https://github.com/octocat/private-repo.git"


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql://x:x@localhost/x",
        redis_url="redis://localhost:6379/0",
        secret_key="s",
        jwt_secret_key="j",
    )


def test_no_recorded_run_anywhere_leaks_the_token_and_shred_precedes_the_scanner_run() -> None:
    fake_runner = FakeContainerRunner()
    fake_runner.script(
        RunResult(exit_code=0, stdout="", stderr="", timed_out=False),  # clone
        RunResult(exit_code=0, stdout="deadbeef1234\n", stderr="", timed_out=False),  # rev-parse
        RunResult(exit_code=0, stdout="[]", stderr="", timed_out=False),  # gitleaks scan
    )
    docker_client = MagicMock()
    created_container = MagicMock()
    docker_client.containers.create.return_value = created_container

    event_log: list[str] = []

    def _containers_run_side_effect(**kwargs: object) -> MagicMock:
        event_log.append("shred" if kwargs.get("entrypoint") == "rm" else "chmod_prep")
        return MagicMock()

    docker_client.containers.run.side_effect = _containers_run_side_effect

    original_run = fake_runner.run
    runner_call_names = iter(["clone", "rev_parse", "scanner"])

    def _tracked_run(**kwargs: object) -> RunResult:
        event_log.append(next(runner_call_names))
        return original_run(**kwargs)  # type: ignore[arg-type]

    fake_runner.run = _tracked_run  # type: ignore[method-assign]

    execution = GitleaksDockerExecution(fake_runner, docker_client, _settings())
    result = execution.execute(
        _PRIVATE_URL,
        "main",
        uuid.uuid4(),
        ScannerType.SECRETS,
        credential=Secret(_TOKEN),
    )

    assert result.head_sha == "deadbeef1234"

    # Ordering proof: chmod prep -> clone -> rev-parse -> shred -> scanner.
    # The shred is strictly before the scanner's RecordedRun is ever created.
    assert event_log == ["chmod_prep", "clone", "rev_parse", "shred", "scanner"]

    # No FakeContainerRunner.RecordedRun (clone, rev-parse, OR scanner) ever
    # carries the token in argv or env.
    assert len(fake_runner.calls) == 3
    for call in fake_runner.calls:
        assert _TOKEN not in " ".join(call.command)
        if call.env:
            assert _TOKEN not in " ".join(call.env.values())

    # The scanner is always the LAST recorded run, and its env is always None
    # — the scanner never receives the credential, only checkout does.
    scanner_call = fake_runner.calls[-1]
    assert scanner_call.env is None
    assert scanner_call.command == [
        "dir",
        "/checkout/checkout",
        "--report-format=json",
        "--report-path=/dev/stdout",
        "--exit-code=2",
        "--no-banner",
    ]

    # The clone call's env is the non-secret path/flag pair only.
    clone_call = fake_runner.calls[0]
    assert clone_call.env == {"HOME": "/workspace", "GIT_TERMINAL_PROMPT": "0"}

    # The token reaches ONLY the put_archive tar payload — never any Docker
    # SDK call's command/environment kwargs on the docker_client double.
    for call in docker_client.containers.run.call_args_list:
        assert _TOKEN not in " ".join(str(v) for v in call.kwargs.get("command", []))
        assert _TOKEN not in str(call.kwargs.get("environment", ""))
    create_kwargs = docker_client.containers.create.call_args.kwargs
    assert _TOKEN not in str(create_kwargs)

    # Sanity check the token WAS actually written (via put_archive only, the
    # one deliberate, in-band, non-argv/non-env channel this design permits).
    _, archive_bytes = created_container.put_archive.call_args.args
    assert _TOKEN.encode() in archive_bytes
