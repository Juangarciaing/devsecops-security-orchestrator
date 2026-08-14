"""Render-and-parse proof that `deploy/kubernetes/base` includes a single-
replica, `Recreate`-strategy Celery Beat Deployment that NEVER mounts or
references the GitHub App private key (github-checks-publisher PR7, design:
"Deployment topology" + "PEM is worker-only, never Beat"). Mirrors
`test_kubernetes_manifests_render.py`'s real `kustomize build` pattern —
skipped if the CLI is not on `PATH`; no live cluster is ever required.

`Recreate` (never the default `RollingUpdate`) is load-bearing here: two
simultaneous Beat replicas would double-schedule every sweep tick, not just
duplicate a stateless request — `Recreate` guarantees the old Pod fully
terminates before a new one starts.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

_KUSTOMIZE = shutil.which("kustomize")
pytestmark = pytest.mark.skipif(_KUSTOMIZE is None, reason="kustomize CLI not on PATH")

REPO_ROOT = Path(__file__).resolve().parents[5]
BASE_DIR = REPO_ROOT / "deploy" / "kubernetes" / "base"

_GITHUB_APP_MARKERS = ("github_app", "github-app", "private-key", "private_key")
_GITHUB_APP_ENV_NAMES = {"GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY_FILE"}


def _build(target: Path) -> list[dict[str, Any]]:
    assert _KUSTOMIZE is not None
    result = subprocess.run(
        [_KUSTOMIZE, "build", str(target)],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return list(yaml.safe_load_all(result.stdout))


def _beat_deployment(docs: list[dict[str, Any]]) -> dict[str, Any]:
    (deployment,) = [doc for doc in docs if doc["kind"] == "Deployment"]
    return deployment


def test_base_renders_exactly_one_deployment_for_celery_beat() -> None:
    docs = _build(BASE_DIR)
    deployments = [doc for doc in docs if doc["kind"] == "Deployment"]

    assert len(deployments) == 1
    assert deployments[0]["metadata"]["name"] == "celery-beat"


def test_beat_deployment_runs_a_single_replica_with_recreate_strategy() -> None:
    deployment = _beat_deployment(_build(BASE_DIR))

    assert deployment["spec"]["replicas"] == 1
    assert deployment["spec"]["strategy"]["type"] == "Recreate"


def test_beat_deployment_never_mounts_or_references_the_github_app_private_key() -> None:
    deployment = _beat_deployment(_build(BASE_DIR))
    pod_spec = deployment["spec"]["template"]["spec"]

    rendered = yaml.safe_dump(pod_spec).lower()
    assert not any(marker in rendered for marker in _GITHUB_APP_MARKERS)

    for container in pod_spec["containers"]:
        env_names = {entry["name"] for entry in container.get("env", [])}
        assert _GITHUB_APP_ENV_NAMES.isdisjoint(env_names)

    for volume in pod_spec.get("volumes", []):
        assert "secret" not in volume


def test_beat_deployment_pods_are_hardened_non_root() -> None:
    deployment = _beat_deployment(_build(BASE_DIR))
    pod_spec = deployment["spec"]["template"]["spec"]
    pod_security = pod_spec["securityContext"]

    assert pod_security["runAsNonRoot"] is True
    assert pod_security["runAsUser"] > 0
    assert pod_security["seccompProfile"]["type"] == "RuntimeDefault"

    (container,) = pod_spec["containers"]
    container_security = container["securityContext"]
    assert container_security["allowPrivilegeEscalation"] is False
    assert container_security["capabilities"]["drop"] == ["ALL"]
    assert container_security["readOnlyRootFilesystem"] is True
