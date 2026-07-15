"""Liveness probe.

`/health` never touches downstream dependencies and always returns 200 while the
process is up. See `/health/ready` (added in a later TDD cycle) for a probe that
also reports Postgres/Redis reachability.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def liveness() -> dict[str, str]:
    return {"status": "ok"}
