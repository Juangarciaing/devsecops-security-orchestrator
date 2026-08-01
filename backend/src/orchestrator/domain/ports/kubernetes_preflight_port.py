"""`ClusterCapabilityPort` — contract for querying whether the target
cluster can PROVE PVC provisioning and NetworkPolicy enforcement, BEFORE the
Kubernetes backend is ever considered available/selectable (Module 13c PR7).

Framework-free, mirroring `ContainerRunnerPort`/`KubernetesJobRunnerPort`:
this module MUST NOT import the `kubernetes` client SDK — only a concrete
adapter would do that (none exists yet; this slice proves the fail-closed
preflight against `tests/fakes/fake_cluster_capability.py` only). Sync, same
rationale as the other blocking-I/O ports in this package.

This port is deliberately narrow: it answers "can this StorageClass and this
namespace prove isolation?", nothing else. It does not create, delete, or
mutate any cluster resource — `kubernetes_preflight.validate_kubernetes_preflight`
(infrastructure layer) is the only caller, and it NEVER submits a Job or PVC
itself (spec's/design's "unproven cluster creates nothing").
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StorageClassInfo:
    """The subset of a `StorageClass`'s shape the preflight needs to prove
    it can provision the exact PVC shape `PvcSpec` requires."""

    name: str
    provisioner: str
    volume_binding_mode: str
    allowed_access_modes: frozenset[str]


class ClusterCapabilityPort(ABC):
    """Contract for the three fail-closed preflight questions: is the target
    namespace's workload identity ready, can the named StorageClass provision
    the required PVC shape, and is NetworkPolicy enforcement confirmed in the
    target namespace?"""

    @abstractmethod
    def namespace_workloads_ready(self, namespace: str) -> bool:
        """Namespace exists, both workload ServiceAccounts exist, and this
        identity is permitted every verb the job runner uses (proven via
        SelfSubjectAccessReview, not by reading Role objects)."""

    @abstractmethod
    def get_storage_class(self, name: str) -> StorageClassInfo | None:
        """Return `name`'s shape, or `None` if it does not exist."""

    @abstractmethod
    def network_policies_enforced(self, namespace: str) -> bool:
        """Whether NetworkPolicy enforcement is confirmed in `namespace`
        (e.g. an enforcing CNI reports isolation is active there)."""
