# DevSecOps Security Orchestrator

A self-hosted platform for orchestrating security scans across registered
Git repositories: register a repo, scan it on demand or automatically on
every push, and triage the findings from a dashboard — with real secret
detection running in hardened, ephemeral containers, not a mock.

Built as a portfolio-grade reference for Clean/Hexagonal architecture, async
task orchestration, and secure-by-design container execution. Delivered in
13 independently-shippable modules via spec-driven development; 12 are
merged as of this README.

## What's actually implemented

- **Auth & RBAC** — JWT (HS256) login, `admin`/`member` roles, admin-only
  user provisioning, reusable FastAPI DI guards.
- **Repository management** — register/list/update/soft-delete GitHub repos;
  identity is `(provider, owner, name)`, credentials are an opaque pointer
  (no secrets manager yet — public repos only for now).
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

Not yet built: a DAST scanner slot (TruffleHog and/or a URL-target scanner
still under consideration), an *outbound* GitHub Checks API integration
(posting scan results back to a PR/commit as a native GitHub check — blocked
on the secrets manager below, since it needs GitHub App/installation-token
auth this project doesn't have; the *internal* policy-gate equivalent is
built, see above), a proper secrets manager for private-repo credentials,
real-time push (still polling), and the observability/Kubernetes-migration
hardening pass — see `## Roadmap` below.

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
| 13 | Hardening & observability (OTel, Prometheus, k8s Jobs migration) | ⏳ |
