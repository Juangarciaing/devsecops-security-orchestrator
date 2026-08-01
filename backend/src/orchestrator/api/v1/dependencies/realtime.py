"""`require_realtime_enabled` (design D-Gate) + `get_relay` (`app.state` accessor).

Listed first in a route's `dependencies=[...]` so FastAPI solves it before
any signature-level dependency (e.g. `get_stream_user`) — no token decode,
no DB query, no relay lookup when the feature is off.
"""

from __future__ import annotations

from fastapi import Depends, Request

from orchestrator.api.v1.errors.problem import ProblemException
from orchestrator.infrastructure.config.settings import Settings, get_settings
from orchestrator.infrastructure.realtime.relay import ScanEventRelay


async def require_realtime_enabled(
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> None:
    if not settings.realtime_enabled:
        raise ProblemException(
            status_code=503, title="Service Unavailable", detail="Realtime updates are disabled"
        )


def get_relay(request: Request) -> ScanEventRelay:
    """Return the app-scoped `ScanEventRelay` set on `app.state` at startup."""
    relay: ScanEventRelay = request.app.state.scan_event_relay
    return relay
