"""`load_kubernetes_config` — explicit in-cluster-first client construction
precedence (k8s-backend-enable PR1, design D-Client).

`kubernetes.config.load_config()`'s own default behavior tries kubeconfig
FIRST and only falls back in-cluster — the wrong precedence here. A worker
Pod that happens to have a stale kubeconfig mounted (e.g. baked into an
image layer, or bind-mounted from a dev host) would silently talk to the
WRONG cluster and create real Jobs/PVCs there. `load_kubernetes_config`
never calls `load_config()`; it probes the in-cluster signals itself and
picks exactly one of the two concrete entry points below.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from kubernetes import config  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from orchestrator.infrastructure.config.settings import Settings

#: The kubelet always projects the Pod's own ServiceAccount token at this
#: fixed path, in every namespace, regardless of ServiceAccount name — the
#: same file `kubernetes.config.incluster_config` itself keys off of
#: internally. Combined with the `KUBERNETES_SERVICE_HOST` env var (also
#: always injected by the kubelet for the Pod's namespace's `kubernetes`
#: Service), both signals together are what "genuinely running in-cluster"
#: means; either alone is not proof (e.g. a stale env var with no real
#: ServiceAccount token mounted).
_SA_TOKEN = "/var/run/secrets/kubernetes.io/serviceaccount/token"


def load_kubernetes_config(settings: Settings) -> None:
    """In-cluster ALWAYS wins over kubeconfig when both in-cluster signals
    are present — see module docstring for why kubeconfig-first precedence
    is unsafe for this use case. Falls back to `load_kube_config`, pinned to
    `settings.kubernetes_kubeconfig_context` (or kubeconfig's own
    `current-context` when unset), only when at least one in-cluster signal
    is missing.
    """
    if os.environ.get("KUBERNETES_SERVICE_HOST") and os.path.exists(_SA_TOKEN):
        config.load_incluster_config()
        return
    config.load_kube_config(context=settings.kubernetes_kubeconfig_context)
