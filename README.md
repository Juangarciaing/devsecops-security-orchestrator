# DevSecOps Security Orchestrator

A self-hosted platform for orchestrating security scans across registered
Git repositories: register a repo, scan it on demand or automatically on
every push, and triage the findings from a dashboard — with real secret
detection running in hardened, ephemeral containers, not a mock.

Built as a portfolio-grade reference for Clean/Hexagonal architecture, async
task orchestration, and secure-by-design container execution. Delivered in
13 independently-shippable modules via spec-driven development; all 13 have
shipped their core scope as of this README (module 11's DAST slot remains
open).

## What's actually implemented

- **Auth & RBAC** — JWT (HS256) login, `admin`/`member` roles, admin-only
  user provisioning, reusable FastAPI DI guards.
- **Repository management** — register/list/update/soft-delete GitHub repos;
  identity is `(provider, owner, name)`. A repository can optionally carry an
  encrypted personal-access-token credential for private scanning (see
  "Private-repository credentials" below).
- **Real scan execution** — four scanners run in hardened, ephemeral sibling
  containers via a shared `ScannerAdapterPort` + registry (`ContainerRunnerPort`
  behind a bounded Docker-socket boundary — the worker holds the socket,
  scanner containers never do): [Gitleaks](https://github.com/gitleaks/gitleaks)
  (secrets), [pip-audit](https://github.com/pypa/pip-audit) (known-CVE Python
  dependency scanning), a pinned, self-built
  [AST-based SAST tool](https://github.com/Juangarciaing/sast-scanner) (custom
  rule-based static analysis), and [Semgrep](https://semgrep.dev) (multi-language
  pattern-based static analysis with community-maintained rulesets, rules baked
  into the image at build time for fully offline, reproducible scans). Each
  addition proved the abstraction: one adapter, one registry entry, one pinned
  Dockerfile — with any real (narrow) orchestration touch (including, for
  Semgrep, a first-of-its-kind schema migration to add its `ScannerType` enum
  value) named honestly rather than glossed over.
- **Async orchestration** — Celery + Redis; a scan is a `ScanRun` with one
  `ScanTask` per scanner, polled from the dashboard, retried with
  exponential backoff on transient failure.
- **Findings** — deduplicated across scans by `(repository, fingerprint)`
  with `first_seen`/`last_seen` tracking, so re-scanning a clean commit
  doesn't spam duplicate rows; suppress/unsuppress workflow; results are
  redacted (no raw secret, snippet, file path/line) for the `member` role.
- **GitHub webhook automation** — `push` to a repo's default branch
  auto-triggers a scan, HMAC-SHA256 verified over the raw body, replay-safe
  (`X-GitHub-Delivery` idempotency), append-only delivery audit log, and a
  hard "never return non-2xx except an invalid signature" contract so
  GitHub doesn't hammer the endpoint with retries.
- **Dashboard** — React 19 + TanStack Query + React Router + shadcn/ui:
  login, repo list/detail, scan trigger with live status polling, findings
  table with suppression, role-aware UI. Repo detail also shows a per-repo
  **trend chart** (finding counts by severity across scans, derived from
  existing `first_seen`/`last_seen` data — no new snapshot table), a
  **diff panel** (added/resolved/carried findings vs. the immediately-previous
  scan, exact by construction since the baseline is always adjacent), and a
  **policy-gate badge** (pass/fail quality gate — fails if any `CRITICAL`/
  `HIGH` finding is open — a fixed global rule, no per-repo config yet).

- **Distributed tracing (Module 13a)** — OpenTelemetry spans correlate a scan
  across process boundaries: API request → Celery enqueue → worker task →
  scanner-container execution → Postgres write-back, exported over OTLP/gRPC
  to a self-hosted Jaeger instance. **Off by default** — no exporter, no
  network call, zero behavior change until `OTEL_EXPORTER_OTLP_ENDPOINT` is
  explicitly set (see "Distributed tracing" below).
- **Prometheus metrics (Module 13b)** — bounded scan-health counters and
  histograms are available through an isolated, opt-in internal scrape path
  (see "Prometheus metrics" below).
- **Kubernetes Jobs execution (Module 13c)** — a complete, fake-client-proven
  Kubernetes backend (split checkout/scanner Jobs sharing one bounded
  ephemeral PVC, RBAC, NetworkPolicy, fail-closed StorageClass/NetworkPolicy
  preflight) exists alongside Docker. **Fail-closed and not yet enabled**:
  selecting it fails worker startup outright, since no adapter is wired to a
  real cluster yet — Docker remains the sole active execution path, unchanged
  (see "Kubernetes Jobs execution" below).
- **Private-repository credentials (secrets manager)** — a repository's
  GitHub personal access token is envelope-encrypted at rest (Fernet, behind
  a framework-free `CredentialStorePort`) and decrypted once per scan inside
  the worker; it is never returned in an API response, log line, span
  attribute, or container argv/`docker inspect` output. Nullable and
  fail-closed: the `credential_encryption_key` setting is optional — an
  unset key leaves public-repo scanning completely unaffected and rejects
  any attempt to store a credential with a clear error. Every decrypt-and-use
  appends one row to an append-only credential-access audit log (repository,
  actor, outcome, timestamp — never the secret). See "Private-repository
  credentials" below.

Not yet built: a DAST scanner slot (TruffleHog and/or a URL-target scanner
still under consideration), an *outbound* GitHub Checks API integration
(posting scan results back to a PR/commit as a native GitHub check — still
blocked on GitHub App/installation-token auth this project doesn't have,
which is a separate concern from the personal-access-token secrets manager
above; the *internal* policy-gate equivalent is built, see above), and
real-time push (still polling). The Kubernetes Jobs backend (Module 13c) is
built and tested but not yet enabled in production — see "Kubernetes Jobs
execution" below and `## Roadmap`.

## Architecture

Hexagonal/Clean layering, shared by both the FastAPI app and the Celery
worker: `domain/` (framework-free entities, value objects, ports) →
`application/` (use cases, orchestrate domain + ports, no framework
imports) → `infrastructure/` (SQLAlchemy repos, Docker container runner,
JWT/password hashing, scanner adapters) → `api/`+`workers/` (driving
adapters — FastAPI routers and Celery tasks call the *same* use cases via
the *same* infrastructure).

```
backend/src/orchestrator/
├── domain/            # entities, value objects, ports — no framework imports
├── application/        # use cases, DTOs, redaction/security logic
├── infrastructure/      # db, container runner, scanners, security, config
├── api/                # FastAPI routers, DI guards, RFC 7807 errors
└── workers/             # Celery app + tasks (same use cases as api/)
```

## Dev setup

```bash
git clone <repo-url> && cd "DevSecOps Security Orchestrator"

# Env files (each documents its own required vars; never commit the real .env)
cp .env.example .env
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env

docker compose up -d
```

### `worker` and the Docker socket (Module 6+)

The `worker` service mounts the host's `/var/run/docker.sock` to launch
hardened scanner containers, and runs as the image's non-root `appuser`
(uid 1000) via `group_add`, not as root. The docker.sock's group GID is
host-specific, so set `DOCKER_GID` in your `.env` to match your host:

```bash
stat -c '%g' /var/run/docker.sock   # Linux
ls -la /var/run/docker.sock         # macOS — read the group column
```

Add `DOCKER_GID=<value>` to `.env` (defaults to `999` if unset, which is a
common but not guaranteed value on many Debian/Ubuntu hosts).

Verify the stack:

```bash
curl -s localhost:8000/health          # {"status":"ok"}
curl -s localhost:8000/health/ready    # 200 once postgres+redis are reachable
```

### Distributed tracing (Module 13a)

The stack always runs a `jaeger` service (`jaegertracing/all-in-one`, UI on
`:16686`, OTLP-gRPC receiver on `:4317`) — but tracing itself is **opt-in**:
`backend`/`worker` read `OTEL_EXPORTER_OTLP_ENDPOINT` from `.env`, and its
default is empty, so a fresh `docker compose up` exports zero spans even
though Jaeger is running. Opt in by adding one line to `.env`:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317
```

Then `docker compose up`, trigger a scan, and open `http://localhost:16686`
— one trace spans the HTTP request (`orchestrator-api`), the Celery task
(`orchestrator-worker`), the `git.checkout` + per-scanner `container.run`
child spans, and the `scan.write_back` Postgres hop. Trace-context
propagation across the API→Celery boundary is automatic
(`opentelemetry-instrumentation-celery`); span shape (names, nesting,
attributes) is verified in CI via `InMemorySpanExporter` — no live Jaeger
required for tests. Delivered in two PRs: PR1 (bootstrap — settings,
`TracerProvider`/OTLP-gRPC exporter, FastAPI/Celery auto-instrumentation,
Celery fork-safety via `worker_process_init`, the `jaeger` compose service)
and PR2 (manual phase spans on the scan task lifecycle, `container.run`/
`git.checkout` spans, a hexagonal-layering guard proving `domain/`/
`application/` stay import-free of `opentelemetry`, this section). Prometheus
metrics (Module 13b) are documented below; the Kubernetes Jobs backend
(Module 13c) has its own section further down.

### Prometheus metrics (Module 13b)

Prometheus is opt-in and internal-only. Start the disposable scrape topology
with `docker compose --profile observability up -d`; the normal `docker compose
up -d` flow does not start Prometheus or the worker exporter. The public API
continues through `http://localhost:8000`, where `/metrics` returns `404`.
Prometheus alone reaches the API exporter (`172.30.0.10:8000/metrics`) and the
worker exporter on the private `observability` network. Prometheus has no host
port and stores TSDB data in `/tmp`, so it has no persistent volume.

| Metric family | Labels / interpretation |
|---|---|
| `orchestrator_api_requests_total` | `method`, route template, `status_class`; excludes `/metrics`. |
| `orchestrator_scan_accepted_total` / `orchestrator_scan_started_total` | `queue`, `scanner_type`; **accepted − started** is the intentionally coarse backlog signal. |
| Retry and terminal counters | Fixed scanner/outcome/failure-category taxonomies; a retry is not terminal failure. |
| Scan/scanner/container histograms | Seconds; terminal `outcome` and bounded `scanner_type` where applicable. |
| Findings and worker processes | Committed findings by scanner; live prefork-worker count. |

Never use repository, scan/run/task, user, container, URL, ref, SHA, path,
exception, evidence, finding content, or credentials as a label. This slice
does not add Grafana, alerts, SLOs, retention policy, Kubernetes discovery,
remote write, or OpenTelemetry Metrics.

**Proof and rollback.** Confirm `/api/v1/targets` shows both scrape targets
`up`, then exercise success, retry, and terminal-failure scans and inspect the
counter/histogram deltas. Confirm host `/metrics` is `404` and an application
network container cannot resolve the private API exporter. If the topology must
be removed, revert the Compose/proxy/Prometheus/exporter assets as one unit;
the base API, worker health endpoints, and Module 13a tracing remain intact.

### Kubernetes Jobs execution (Module 13c)

An alternative Kubernetes Jobs execution backend was built alongside Docker,
delivered as eight sequential PRs: descriptor-based Docker execution per
scanner (PR1-4), parser/security test contracts plus legacy and compatibility
API removal (PR5a-c), a two-Job split lifecycle behind a fake Kubernetes
client (PR6), Kustomize/RBAC/NetworkPolicy manifests and a fail-closed
StorageClass/NetworkPolicy preflight (PR7), and backend-selection wiring plus
orphan reconciliation (PR8).

The design: one checkout Job (owns clone credentials, narrow Git+DNS egress)
and one scanner Job (zero credentials, zero egress) share a single bounded,
per-scan `ReadWriteOnce`/`WaitForFirstConsumer` PVC — checkout mounts it
read-write, the scanner read-only. Private repositories fail before any
workload is created. Jobs run non-root with dropped capabilities, no privilege
escalation, `RuntimeDefault` seccomp, read-only root filesystem,
`backoffLimit: 0`, and TTL cleanup; Celery is the sole retry authority — a
Kubernetes-selected scan never silently falls back to Docker mid-run.

**Not yet enabled.** Setting `scan_execution_backend=kubernetes` currently
fails worker startup on purpose: `ClusterCapabilityPort`/`KubernetesJobRunnerPort`
are proven only against fakes (`FakeClusterCapabilityPort`/
`FakeKubernetesJobRunner`) in CI — no adapter is wired to a real cluster yet.
Docker stays the default and the only backend that actually runs scans; an
`OPTIONAL` `kind`/`k3d` live-cluster proof from the original spec was not
exercised. Known follow-up work, tracked for whichever future module adds a
real cluster adapter: the adapter itself; wiring job-outcome telemetry/tracer
spans from inside the executor (the metric functions exist and are tested,
just not called from a live scan yet); an explicit `HOME` env var on the
checkout Job's non-root git container (unprovable without a real cluster);
and a scheduler/runbook trigger for the reconciliation sweep (the sweep logic
itself is idempotent and tested).

`deploy/kubernetes/` holds the Kustomize base and an example overlay; render
it locally with `kustomize build deploy/kubernetes/overlays/example` — no
cluster access required, it's static rendering.

### Private-repository credentials

Cross-cutting addition delivered after the original 13-module plan (not a
"Module 14" — it touches `domain/`, `application/`, `infrastructure/`,
`workers/`, the DB schema, and the frontend, the same way Modules 13a-c did).
A `CodeRepository` can now carry one GitHub personal access token so private
repos can be scanned end to end.

**Setup.** Set `credential_encryption_key` in `backend/.env` to a urlsafe-base64,
32-byte Fernet key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

This setting is **nullable and fail-closed**: leave it unset and every
public-repo behavior stays byte-for-byte unchanged (no credential can ever be
stored). Once set, registering or updating a repository with a
`credential` field encrypts it (Fernet, envelope-style) before it ever
reaches the database; every read/list response exposes only
`has_credential`/`credential_kind`, never the plaintext value. Only GitHub
repositories may carry a credential — a credential submitted for any other
provider is rejected before encryption.

**Delivery.** The token reaches the checkout container as a git-credential-store
file streamed over the Docker API (`put_archive`), never as `clone_url` argv,
an environment variable, or a `docker inspect`-visible value; the file is
shredded before the workspace is ever handed to a scanner container.

**Audit log.** Every time a stored credential is decrypted for a scan, exactly
one append-only row is written (repository, actor — `"webhook"` or the
triggering user — outcome, timestamp). A decrypt failure (wrong/rotated key)
fails that one scan with a credential-free error and leaves the repository
`is_active=true`; it is never auto-deactivated.

## Tests

```bash
cd backend && uv run pytest -v
cd frontend && npm run test
```

## CI / pre-commit

`.github/workflows/ci.yml` runs backend (ruff, mypy, pytest), frontend
(eslint, prettier, tsc, vitest), and `docker compose config -q` on every push
and pull request. `.pre-commit-config.yaml` mirrors the same checks locally
(`pre-commit install` once, then `pre-commit run --all-files` to check
everything).

## Roadmap

Built in 13 sequential, independently-shippable modules (see `.atl/` /
project SDD history for the full spec/design trail per module).

| # | Module | Status |
|---|--------|--------|
| 1 | Project skeleton & CI baseline | ✅ |
| 2 | Domain & persistence foundation | ✅ |
| 3 | AuthN/AuthZ | ✅ |
| 4 | Repository ingestion (manual CRUD) | ✅ |
| 5 | Scan orchestration skeleton | ✅ |
| 6 | One real scanner end-to-end (Gitleaks) | ✅ |
| 7 | Normalization/adapter layer + dedup | ✅ |
| 8 | Results API | ✅ |
| 9 | Dashboard MVP | ✅ |
| 10 | Webhook handling (GitHub push) | ✅ |
| 11 | More scanners (pip-audit ✅, AST-SAST ✅, Semgrep ✅, DAST slot pending) | ⏳ |
| 12 | Advanced dashboard (trends ✅, diffing ✅, internal policy gate ✅; outbound GitHub Checks API deferred) | ✅ |
| 13 | Hardening & observability (13a: OTel distributed tracing ✅; 13b: Prometheus metrics ✅; 13c: Kubernetes Jobs backend ✅ built, fail-closed pending a real cluster adapter) | ✅ |
