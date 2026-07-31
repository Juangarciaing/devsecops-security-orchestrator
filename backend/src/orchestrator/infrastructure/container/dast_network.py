"""`ensure_dast_network` — idempotent creation of the dedicated, non-default
Docker bridge network every ZAP scan container joins (dast-scanner design
D4, PR5b).

Network *creation* is deliberately NOT `ContainerRunnerPort.run()`'s job
(that port takes a `network_name`, not a policy) — this module is the one
place that policy lives. What this actually buys (stated precisely, not
overclaimed, per design D4): Docker's `DOCKER-ISOLATION-STAGE-1/2` iptables
chains DROP traffic between distinct bridge networks by default, and
compose service names do not resolve outside the compose network — so a
container on this network cannot reach `postgres`/`redis`/`api` by name or
by compose-bridge IP, even if URL/DNS validation is bypassed. It does NOT
block the docker0 gateway or the host LAN; private-range egress remains the
DNS guardrail's job (`infrastructure.security.dns_target_resolver`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import docker.errors

if TYPE_CHECKING:
    from docker import DockerClient

    from orchestrator.infrastructure.config.settings import Settings


class DastNetworkUnavailableError(Exception):
    """Raised when the dedicated DAST Docker network cannot be confirmed or
    created — fail closed (design D4): no ZAP container may ever launch
    without this network existing."""


def ensure_dast_network(docker_client: DockerClient, settings: Settings) -> str:
    """Idempotently ensure `settings.dast_network_name` exists as a
    non-attachable bridge network, and return its name.

    Safe to call repeatedly: an existing network with this name is reused
    (`networks.create` is never called again), never recreated or
    duplicated. `attachable=False` means no OTHER container may `docker
    network connect` onto it out-of-band — only containers this
    orchestrator explicitly joins via `ContainerRunnerPort.run(network_name=
    ...)` can ever be on it.
    """
    name = settings.dast_network_name
    try:
        existing = docker_client.networks.list(names=[name])
        if existing:
            return name
        docker_client.networks.create(
            name, driver="bridge", attachable=False, check_duplicate=True
        )
    except docker.errors.APIError as exc:
        raise DastNetworkUnavailableError(
            f"failed to ensure the dedicated DAST network {name!r}: {exc}"
        ) from exc
    return name
