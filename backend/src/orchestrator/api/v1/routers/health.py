"""Liveness and readiness probes.

`/health` never touches downstream dependencies and always returns 200 while the
process is up. `/health/ready` additionally reports whether Postgres and Redis are
reachable, returning 503 when either is down.
"""

from __future__ import annotations

import socket
from urllib.parse import urlparse

from fastapi import APIRouter, Response

from orchestrator.infrastructure.config.settings import get_settings

router = APIRouter(tags=["health"])


def _tcp_reachable(url: str, timeout: float = 1.0) -> bool:
    """Best-effort TCP-level reachability check for a dependency URL's host:port."""
    parsed = urlparse(url)
    if parsed.hostname is None or parsed.port is None:
        return False
    try:
        with socket.create_connection((parsed.hostname, parsed.port), timeout=timeout):
            return True
    except OSError:
        return False


@router.get("/health")
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def readiness(response: Response) -> dict[str, str]:
    settings = get_settings()
    database_up = _tcp_reachable(settings.database_url)
    redis_up = _tcp_reachable(settings.redis_url)
    ready = database_up and redis_up

    response.status_code = 200 if ready else 503
    return {
        "status": "ok" if ready else "unavailable",
        "database": "up" if database_up else "down",
        "redis": "up" if redis_up else "down",
    }
