"""RED/GREEN — explicit in-cluster-first client config precedence
(k8s-backend-enable PR1, design D-Client).

`kubernetes.config.load_config()`'s own default behavior is kubeconfig-first
with an in-cluster fallback — the WRONG precedence for a worker Pod that may
have a stale kubeconfig mounted (it would silently target the wrong cluster
and create real workloads there). `load_kubernetes_config` inverts this
explicitly: an in-cluster signal (`KUBERNETES_SERVICE_HOST` env var AND the
projected ServiceAccount token file) ALWAYS wins over kubeconfig, and only
one of the two `kubernetes.config` entry points is ever invoked.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from orchestrator.infrastructure.config.settings import Settings
from orchestrator.infrastructure.kubernetes.kubernetes_client_factory import (
    _SA_TOKEN,
    load_kubernetes_config,
)

_FACTORY = "orchestrator.infrastructure.kubernetes.kubernetes_client_factory"


def _settings(*, kubeconfig_context: str | None = None) -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql://o:o@localhost/o",
        redis_url="redis://localhost:6379/0",
        secret_key="s",
        jwt_secret_key="j",
        kubernetes_kubeconfig_context=kubeconfig_context,
    )


def test_in_cluster_signals_present_uses_incluster_config_never_kubeconfig(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    with (
        patch(f"{_FACTORY}.os.path.exists", return_value=True) as mock_exists,
        patch(f"{_FACTORY}.config.load_incluster_config") as mock_incluster,
        patch(f"{_FACTORY}.config.load_kube_config") as mock_kubeconfig,
    ):
        load_kubernetes_config(_settings())

    mock_exists.assert_called_once_with(_SA_TOKEN)
    mock_incluster.assert_called_once_with()
    mock_kubeconfig.assert_not_called()


def test_missing_env_var_falls_back_to_pinned_kubeconfig_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    with (
        patch(f"{_FACTORY}.config.load_incluster_config") as mock_incluster,
        patch(f"{_FACTORY}.config.load_kube_config") as mock_kubeconfig,
    ):
        load_kubernetes_config(_settings(kubeconfig_context="kind-devsecops-orchestrator"))

    mock_incluster.assert_not_called()
    mock_kubeconfig.assert_called_once_with(context="kind-devsecops-orchestrator")


def test_absent_kubeconfig_context_defers_to_current_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    with (
        patch(f"{_FACTORY}.config.load_incluster_config") as mock_incluster,
        patch(f"{_FACTORY}.config.load_kube_config") as mock_kubeconfig,
    ):
        load_kubernetes_config(_settings(kubeconfig_context=None))

    mock_incluster.assert_not_called()
    mock_kubeconfig.assert_called_once_with(context=None)


def test_env_var_present_but_token_file_missing_falls_back_to_kubeconfig(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale env var alone — without a genuinely projected ServiceAccount
    token — must NOT be enough to trust the in-cluster path. Both signals are
    required, never just one."""
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    with (
        patch(f"{_FACTORY}.os.path.exists", return_value=False),
        patch(f"{_FACTORY}.config.load_incluster_config") as mock_incluster,
        patch(f"{_FACTORY}.config.load_kube_config") as mock_kubeconfig,
    ):
        load_kubernetes_config(_settings())

    mock_incluster.assert_not_called()
    mock_kubeconfig.assert_called_once_with(context=None)
