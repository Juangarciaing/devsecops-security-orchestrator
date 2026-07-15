# DevSecOps Security Orchestrator

Module 1 walking skeleton: a runnable Docker Compose stack (postgres, redis,
backend, frontend), CI/pre-commit quality gates, a liveness `/health`
endpoint, and the hexagonal folder shape later modules build on. No domain
logic, auth, or scanning yet — see `backend/src/orchestrator/` and
`frontend/src/` for the empty-but-real package layout.

## Dev setup

```bash
git clone <repo-url> && cd "DevSecOps Security Orchestrator"

# Env files (each documents its own required vars; never commit the real .env)
cp .env.example .env
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env

docker compose up -d
```

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
