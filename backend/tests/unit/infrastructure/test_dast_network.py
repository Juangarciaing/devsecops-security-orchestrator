"""`ensure_dast_network` (dast-scanner design D4, PR5b task 5.11): idempotent
creation of the dedicated, non-attachable Docker bridge network every ZAP
scan container joins — never the compose default bridge."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import docker.errors
import pytest

from orchestrator.infrastructure.container.dast_network import (
    DastNetworkUnavailableError,
    ensure_dast_network,
)


def _settings() -> SimpleNamespace:
    return SimpleNamespace(dast_network_name="dast-scan-net")


def test_ensure_dast_network_creates_a_non_attachable_bridge_when_absent() -> None:
    client = MagicMock()
    client.networks.list.return_value = []

    name = ensure_dast_network(client, _settings())

    assert name == "dast-scan-net"
    client.networks.create.assert_called_once_with(
        "dast-scan-net", driver="bridge", attachable=False, check_duplicate=True
    )


def test_ensure_dast_network_is_idempotent_when_already_present() -> None:
    """Safe to call repeatedly: an existing network with this name is
    reused, never recreated or duplicated."""
    client = MagicMock()
    client.networks.list.return_value = [MagicMock()]

    name = ensure_dast_network(client, _settings())

    assert name == "dast-scan-net"
    client.networks.create.assert_not_called()


def test_ensure_dast_network_fails_closed_on_docker_api_error() -> None:
    """Design D4: no ZAP container may ever launch without this network
    existing — a Docker API failure here must propagate as a clear,
    deterministic error, never be swallowed."""
    client = MagicMock()
    client.networks.list.side_effect = docker.errors.APIError("daemon unreachable")

    with pytest.raises(DastNetworkUnavailableError, match="dast-scan-net"):
        ensure_dast_network(client, _settings())

    client.networks.create.assert_not_called()


def test_ensure_dast_network_fails_closed_when_create_itself_errors() -> None:
    client = MagicMock()
    client.networks.list.return_value = []
    client.networks.create.side_effect = docker.errors.APIError("permission denied")

    with pytest.raises(DastNetworkUnavailableError, match="dast-scan-net"):
        ensure_dast_network(client, _settings())
