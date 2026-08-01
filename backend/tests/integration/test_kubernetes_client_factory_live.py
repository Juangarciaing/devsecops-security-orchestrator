"""Live-cluster proof for k8s-backend-enable PR1 (task 1.7) — REAL API
server, no mocks.

Confirms, against the real `kind-devsecops-orchestrator` cluster:
- `load_kubernetes_config` with a pinned `kubernetes_kubeconfig_context`
  genuinely constructs a client that talks to the real API server (not just
  that the right `kubernetes.config` function was called, as the unit tests
  already prove with mocks)
- the in-cluster-first precedence codepath is exercised too, standing in for
  a real Pod environment via monkeypatched env var + a temp SA-token-shaped
  file, since this test process itself never runs inside a Pod

Skips automatically if the `kind-devsecops-orchestrator` context is not
reachable — mirrors `test_docker_container_runner_live.py`'s
skip-when-unreachable convention.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes.config.config_exception import ConfigException

from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.kubernetes.kubernetes_client_factory import (
    load_kubernetes_config,
)

pytestmark = pytest.mark.integration

_CONTEXT = "kind-devsecops-orchestrator"
_NAMESPACE = "security-scans"


def _settings(*, kubeconfig_context: str | None = _CONTEXT) -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql://o:o@localhost/o",
        redis_url="redis://localhost:6379/0",
        secret_key="s",
        jwt_secret_key="j",
        kubernetes_kubeconfig_context=kubeconfig_context,
    )


@pytest.fixture
def live_cluster() -> Iterator[None]:
    """Skip the whole module if `kind-devsecops-orchestrator` isn't reachable."""
    try:
        k8s_config.load_kube_config(context=_CONTEXT)
        k8s_client.CoreV1Api().list_namespace(_request_timeout=5)
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"kind-devsecops-orchestrator cluster not reachable: {exc}")
    yield


def test_pinned_kubeconfig_context_connects_and_lists_namespaces(live_cluster: None) -> None:
    load_kubernetes_config(_settings(kubeconfig_context=_CONTEXT))

    namespaces = [ns.metadata.name for ns in k8s_client.CoreV1Api().list_namespace().items]

    assert _NAMESPACE in namespaces


def test_pinned_context_reads_the_real_scan_workspace_storage_class(live_cluster: None) -> None:
    """Genuinely exercises the constructed client against a second API group
    (`StorageV1Api`), not just `CoreV1Api` — confirms the client config is
    wired for the whole API surface future PRs' adapters will need."""
    load_kubernetes_config(_settings(kubeconfig_context=_CONTEXT))

    storage_classes = [
        sc.metadata.name for sc in k8s_client.StorageV1Api().list_storage_class().items
    ]

    assert "scan-workspace" in storage_classes


def test_absent_context_uses_kubeconfigs_own_current_context(live_cluster: None) -> None:
    """`kubernetes_kubeconfig_context=None` must still reach the real API
    server via kubeconfig's own `current-context` — proven live, not just
    asserted against a mock call signature."""
    load_kubernetes_config(_settings(kubeconfig_context=None))

    namespaces = [ns.metadata.name for ns in k8s_client.CoreV1Api().list_namespace().items]

    assert _NAMESPACE in namespaces


def test_in_cluster_signals_win_over_kubeconfig_even_when_both_are_present(
    live_cluster: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulates a genuinely in-cluster environment (both signals present)
    standing in front of a VALID, reachable kubeconfig context — proves the
    precedence live: `load_kubernetes_config` must genuinely attempt (and
    fail on) the real `kubernetes.config.load_incluster_config()` codepath —
    this test process is not really running in a Pod, so no real
    `ca.crt`/token exist at the client's hardcoded ServiceAccount paths —
    rather than silently falling through to the working, reachable
    kubeconfig context, which would swallow the failure and hide the wrong
    precedence."""
    fake_token = tmp_path / "token"
    fake_token.write_text("not-a-real-token")
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "203.0.113.1")  # TEST-NET-3, unroutable
    monkeypatch.setenv("KUBERNETES_SERVICE_PORT", "443")

    with (
        patch(
            "orchestrator.infrastructure.kubernetes.kubernetes_client_factory._SA_TOKEN",
            str(fake_token),
        ),
        pytest.raises(ConfigException),
    ):
        load_kubernetes_config(_settings(kubeconfig_context=_CONTEXT))
