"""Live-Docker proof for Module 11 PR2 (AST-SAST adapter, D5/Phase 5) — REAL
Docker socket, REAL locally-built `sast-scanner:local` image, REAL
`GitCheckout` clone (no mocks, no synthetic fixture volumes).

Unlike `test_gitleaks_adapter_live.py`/`test_pip_audit_adapter_live.py`
(which bypass `GitCheckout` with a throwaway fixture-volume container
holding hand-written content), this file drives the REAL `GitCheckout`/
`DockerContainerRunner` checkout path against a real public GitHub
repository — the adapter's real-world proof needs genuine third-party repo
content, not a fixture this repo controls. Mirrors
`test_docker_container_runner_live.py`'s `GitCheckout` usage combined with
the adapter-live-test structure (`docker_client` fixture, `_settings()`).

## Honest correction of a stale premise (surfaced, not silently absorbed)
The apply batch this file was written under asserted `secure-task-api` has a
documented SAST-020 (SQL injection) finding at `app/routes/auth.py:43` and
`app/routes/users.py:27`. Verified directly against the REAL pinned image and
the REAL current `secure-task-api` HEAD (a single-commit repo, `d9d0787` —
`git log --all` confirms no other history/tags/branches exist to have
produced a different "prior manual run"): that claim does NOT hold. Both
lines are `', '.join(VALID_ROLES)` calls inside an f-string. `sast-scanner`'s
`SQL_KEYWORDS` regex (`sast/checks/sql_injection.py`) carries an explicit
negative lookbehind `(?<!\\.)` specifically designed to exclude
`str.join()`/`str.format()` method calls from matching — reproduced directly
against the exact source line with the exact regex (`re.search` -> `None`)
AND against the real pinned image (0 `SAST-020` findings across the whole
repo). The app's own docstring is accurate: "SQL injection is prevented
structurally by always going through the SQLAlchemy ORM ... never by
string-formatting SQL." `secure-task-api` has exactly ONE real, verified
finding: `SAST-030` ("Flask: debug=True en app.run()", HIGH) at `run.py:12`
(`app.run(debug=True)`). This file proves detection against THAT real
finding rather than fabricating or planting content to match the stale
premise.

Skips automatically if no Docker socket is reachable (`client.ping()`
fails), matching `test_docker_container_runner_live.py`'s pattern.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import docker
import pytest

from orchestrator.domain.value_objects.enums import FindingSeverity
from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.container.docker_container_runner import DockerContainerRunner
from orchestrator.infrastructure.scanners.ast_sast_adapter import AstSastAdapter
from orchestrator.infrastructure.vcs.git_checkout import GitCheckout

pytestmark = pytest.mark.integration

#: Public fixture repo with exactly one verified real finding (see module
#: docstring): `SAST-030` (`app.run(debug=True)`) at `run.py:12`.
_SECURE_TASK_API_URL = "https://github.com/Juangarciaing/secure-task-api.git"
_SECURE_TASK_API_REF = "main"

#: Public repo with zero Python files at all (D6/spec's zero-findings
#: success contract) — the same octocat fixture
#: `test_docker_container_runner_live.py` already uses for `GitCheckout`.
_NO_PYTHON_REPO_URL = "https://github.com/octocat/Hello-World.git"
_NO_PYTHON_REPO_REF = "master"


def _live_docker_client() -> docker.DockerClient:
    client = docker.from_env()
    client.ping()
    return client


@pytest.fixture
def docker_client() -> Iterator[docker.DockerClient]:
    try:
        client = _live_docker_client()
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"no reachable Docker socket: {exc}")
    yield client
    client.close()


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql://x:x@localhost/x",
        redis_url="redis://localhost:6379/0",
        secret_key="s",
        jwt_secret_key="j",
    )


def test_ast_sast_adapter_detects_a_real_finding_via_real_docker_and_real_checkout(
    docker_client: docker.DockerClient,
) -> None:
    settings = _settings()
    runner = DockerContainerRunner(client=docker_client)
    checkout = GitCheckout(runner=runner, docker_client=docker_client, settings=settings)

    with checkout.checkout(_SECURE_TASK_API_URL, _SECURE_TASK_API_REF) as workspace:
        adapter = AstSastAdapter(runner=runner, settings=settings)

        result = adapter.scan(workspace.volume_name)
        assert result.timed_out is False

        scan_task_id = uuid.uuid4()
        findings = adapter.parse(result, scan_task_id)

    assert len(findings) >= 1
    finding = findings[0]
    assert finding.scan_task_id == scan_task_id
    # Real sast-scanner output for the current secure-task-api HEAD (captured
    # directly, not assumed): `rule_id="SAST-030"`, `severity="ALTA"` ->
    # HIGH, `file="/checkout/checkout/run.py"` -> normalized `"run.py"`,
    # `line=12` (`app.run(debug=True)`).
    assert finding.rule_id == "SAST-030"
    assert finding.severity == FindingSeverity.HIGH
    assert finding.file_path == "run.py"
    assert finding.line_number == 12
    assert finding.fingerprint

    remaining = docker_client.containers.list(
        all=True, filters={"ancestor": settings.scan_sast_image}
    )
    assert remaining == [], "sast-scanner container was not force-removed after completion"


def test_ast_sast_adapter_reports_zero_findings_and_completes_on_a_no_python_repo(
    docker_client: docker.DockerClient,
) -> None:
    """Spec's "Zero-Findings Success Contract": a repo with no Python source
    MUST produce zero `Finding`s, never a `SastFailedError` — proven here
    against a REAL repo with genuinely zero `.py` files, not a mock."""
    settings = _settings()
    runner = DockerContainerRunner(client=docker_client)
    checkout = GitCheckout(runner=runner, docker_client=docker_client, settings=settings)

    with checkout.checkout(_NO_PYTHON_REPO_URL, _NO_PYTHON_REPO_REF) as workspace:
        adapter = AstSastAdapter(runner=runner, settings=settings)

        result = adapter.scan(workspace.volume_name)
        assert result.timed_out is False

        findings = adapter.parse(result, uuid.uuid4())

    assert findings == []
