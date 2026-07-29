"""`FakeClusterCapabilityPort` — in-memory `ClusterCapabilityPort` test
double. Mirrors `FakeKubernetesJobRunner`'s conventions: tests seed exactly
the StorageClass/namespace state they need, WITHOUT a real Kubernetes API
server.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from orchestrator.domain.ports.kubernetes_preflight_port import (
    ClusterCapabilityPort,
    StorageClassInfo,
)


@dataclass(slots=True)
class FakeClusterCapabilityPort(ClusterCapabilityPort):
    """In-memory `ClusterCapabilityPort`. Seed state before calling."""

    _storage_classes: dict[str, StorageClassInfo] = field(default_factory=dict, repr=False)
    _enforced_namespaces: set[str] = field(default_factory=set, repr=False)

    def seed_storage_class(self, info: StorageClassInfo) -> None:
        self._storage_classes[info.name] = info

    def seed_enforced_namespace(self, namespace: str) -> None:
        self._enforced_namespaces.add(namespace)

    def get_storage_class(self, name: str) -> StorageClassInfo | None:
        return self._storage_classes.get(name)

    def network_policies_enforced(self, namespace: str) -> bool:
        return namespace in self._enforced_namespaces
