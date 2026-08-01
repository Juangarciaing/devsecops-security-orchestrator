# Kubernetes execution backend — operator prerequisites

This runbook is for an operator who wants to run `scan_execution_backend=
kubernetes` for real, against a real cluster. It is not a design document —
see the `k8s-backend-enable` change's spec/design for rationale. Every item
below is a hard requirement unless stated otherwise; the backend has been
proven end to end against a real `kind` cluster running Calico, and every
gap called out here was found (and, where fixable, fixed) during that proof.

## 1. The cluster's CNI MUST enforce `NetworkPolicy` — not just accept it

The isolation guarantee this backend depends on (scanner Jobs have zero
egress, checkout Jobs may only reach Git+DNS) is enforced entirely by two
`NetworkPolicy` objects (`deploy/kubernetes/base/networkpolicies.yaml`).
**A Kubernetes cluster can accept `NetworkPolicy` objects into its API and
enforce none of them.** `kind`'s default CNI, `kindnetd`, is exactly this
case: `kubectl apply` succeeds, the objects exist, and every Pod still has
full egress. This is not specific to this project's dev setup — it is true
of any cluster whose CNI does not implement NetworkPolicy enforcement
(the stock `kindnetd`, some minimal/embedded CNIs, etc.).

This project's own `kind` cluster (`kind-devsecops-orchestrator`) required:

- `disableDefaultCNI: true` in the `kind` cluster config, so `kindnetd`
  never installs.
- A `podSubnet` compatible with the replacement CNI (`192.168.0.0/16` was
  used here).
- [Calico](https://www.tigera.io/project-calico/) installed separately
  (v3.32.1, via the Tigera operator) as the actual NetworkPolicy-enforcing
  CNI.

Whatever cluster this backend runs against, confirm its CNI genuinely
enforces `NetworkPolicy` before trusting it — see section 4 below for how
this platform's preflight check treats that claim.

## 2. Apply the manifests with `kubectl apply -k`, never `-f` on individual files

```bash
kubectl apply -k deploy/kubernetes/base/
```

Do **not** run `kubectl apply -f deploy/kubernetes/base/namespace.yaml`,
`-f .../rbac.yaml`, etc. one file at a time. This was a real mistake made
(and fixed) earlier in this project's own history: the Kustomize
`namespace:` transformer in `kustomization.yaml` (`namespace:
security-scans`) only runs when Kustomize itself renders the resources —
i.e. when you invoke it via `-k`. Apply the individual YAML files directly
and every namespaced resource keeps whatever `metadata.namespace` (or lack
of one) is literally written in the file, silently diverging from what the
kustomization declares.

`kubectl apply -k deploy/kubernetes/base/` applies, in one shot: the
`security-scans` namespace, the `checkout`/`scanner` workload
ServiceAccounts, the `scan-job-runner` Role/RoleBindings, the
`scan-orchestrator` orchestrator identity (Role + the one narrow read-only
ClusterRole — see section 3), both NetworkPolicies, and the example
PVC/Job manifests.

## 3. StorageClass naming — `scan-workspace` is an example, not a requirement

`scan-workspace` is the literal StorageClass name used throughout this
codebase's example manifests (`deploy/kubernetes/base/pvc.yaml`) and its
test suite. It matches nothing intrinsic to Kubernetes — it is simply
whatever string `settings.kubernetes_storage_class_name` is configured to.

Any StorageClass name works, on any provisioner, **as long as it is
configured consistently**:

- `settings.kubernetes_storage_class_name` (required whenever
  `scan_execution_backend=kubernetes` — `Settings()` fails fast at
  construction time otherwise) must name a StorageClass that actually
  exists in the target cluster.
- That StorageClass must support `ReadWriteOnce` access (universal across
  provisioners) and, ideally, `WaitForFirstConsumer` binding (the fail-closed
  preflight checks for existence and binding mode; see `kubernetes_preflight.py`).
- The verified local `kind` setup aliases `scan-workspace` onto
  `rancher.io/local-path`, `kind`'s own default provisioner — a real cluster
  might use `ebs.csi.aws.com`, `pd.csi.storage.gke.io`, or anything else.
  Nothing in this backend cares which provisioner backs the name.

## 4. kubeconfig, RBAC, and identity precedence

The client-config precedence, in order, is:

1. **In-cluster ALWAYS wins.** If `KUBERNETES_SERVICE_HOST` is set and the
   ServiceAccount token file
   (`/var/run/secrets/kubernetes.io/serviceaccount/token`) exists, the
   orchestrator process authenticates as whatever ServiceAccount its own
   Pod is bound to — this should be `scan-orchestrator`
   (`deploy/kubernetes/base/orchestrator-rbac.yaml`), never a workload SA
   (`checkout`/`scanner`, both `automountServiceAccountToken: false` by
   design).
2. Otherwise, kubeconfig is used, pinned to
   `settings.kubernetes_kubeconfig_context` (`None` means "use kubeconfig's
   own `current-context`" — deliberately unpinned by default is a real
   hazard for a tool whose job is *creating* workloads; pin it explicitly
   in any shared dev environment).

`scan-orchestrator` (distinct from the workload SAs) is the identity the
orchestrator process itself authenticates as to create/poll/delete Jobs and
PVCs, read Pod logs, and confirm StorageClass/NetworkPolicy/namespace shape
during preflight. It is granted a namespaced Role (jobs/pvcs/pods/pods-log,
`list` on NetworkPolicies, `get` on ServiceAccounts) plus exactly one
narrow, read-only ClusterRole (`get`/`list` on `storageclasses`, `get` on
`namespaces` pinned via `resourceNames: ["security-scans"]`) — both
cluster-scoped resources with no namespaced equivalent. Nothing about this
identity is optional: `namespace_workloads_ready()` (the first preflight
check, run before StorageClass/NetworkPolicy) fails closed if the
`scan-orchestrator` identity cannot pass a `SelfSubjectAccessReview` for
every verb the job runner uses.

## 5. Be honest about `kubernetes_cni_enforces_network_policy`

`kubernetes_cni_enforces_network_policy` (default `False`, fail-closed) is
an **operator attestation**, not a technical check. Setting it to `true`
tells this platform's preflight "trust that this cluster's CNI enforces
NetworkPolicy" — the platform then goes on to verify the *shape* of the
two policy objects (they exist, they select the right Pods, `scanner-egress`
is genuinely total-deny), but it has **no way to independently confirm the
CNI itself honors any of it**. A cluster running unmodified `kindnetd` with
this flag set to `true` will pass preflight and then leak scanner egress
in reality, silently.

Before setting this to `true`, the operator MUST independently verify their
own cluster's CNI actually enforces NetworkPolicy — e.g. the live proof this
project ran: create a Pod carrying the `scanner-egress` policy's selector
labels and confirm its outbound connections genuinely fail. Do not set this
flag based on the CNI's marketing claims or documentation alone; verify it
against the actual running cluster.

## 6. The `kind load docker-image` gap

The Docker execution backend uses the local Docker daemon's own image
cache directly — a locally-built image (`docker build -t foo:local .`) is
immediately runnable by `docker.from_env()` with zero extra steps. A `kind`
cluster's containerd runtime does **not** share that cache: a `kind` node
cannot pull an image that was only ever built locally and never pushed to
a registry it can reach.

This backend's own images are, by design, unaffected in the common case:
`checkout_image`/`scan_git_image` (`alpine/git`, pinned by digest) and the
one registered Kubernetes scanner image (`scan_container_image`, Gitleaks,
also pinned by digest — `kubernetes_scanner_descriptor.py` registers
**only** `ScannerType.SECRETS`) are both public-registry images pulled the
normal way; nothing about them needs `kind load`.

The gap is real for anything built locally that isn't already covered by
that registration — e.g. any future Kubernetes scanner descriptor pointing
at one of this project's own locally-built images
(`pip-audit-scanner:local`, `sast-scanner:local`, `semgrep-scanner:local`,
`zap-scanner:local`). Before wiring any such image into the Kubernetes
path, either:

- push it to a registry the cluster can reach and reference it by that
  registry path, or
- explicitly load it into the cluster's own containerd:
  `kind load docker-image <image>:<tag> --name devsecops-orchestrator`.

There is no third option — `kind`'s node will report `ErrImagePull`/
`ImagePullBackOff` for a locally-built, unpushed, un-loaded image every
time.
