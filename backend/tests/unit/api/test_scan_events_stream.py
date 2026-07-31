"""`GET /scans/{scan_run_id}/events` — SSE route (design D-Transport/D-Gate).

No `pytest-asyncio` plugin: `_frame` is tested as a bare sync call; the full
route is tested through `fastapi.testclient.TestClient`, which drives the
ASGI app on its own event loop.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

import orchestrator.api.v1.dependencies.auth as auth_module
import orchestrator.api.v1.routers.scans as scans_module
from orchestrator.api.main import create_app
from orchestrator.api.v1.routers.scans import _frame
from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.entities.user import User
from orchestrator.domain.value_objects.enums import ScanRunStatus, UserRole
from orchestrator.infrastructure.realtime.events import ScanStatusEvent
from orchestrator.infrastructure.security.jwt import create_access_token


def test_frame_produces_the_exact_sse_shape() -> None:
    assert _frame("scan.status", '{"a":1}') == 'event: scan.status\ndata: {"a":1}\n\n'


def _make_user() -> User:
    now = datetime.now(UTC).replace(tzinfo=None)
    return User(
        id=uuid.uuid4(),
        email="user@example.com",
        hashed_password="irrelevant",
        role=UserRole.MEMBER,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def _make_scan_run(scan_run_id: uuid.UUID) -> ScanRun:
    now = datetime.now(UTC).replace(tzinfo=None)
    return ScanRun(
        id=scan_run_id,
        repository_id=uuid.uuid4(),
        scan_target_id=None,
        status=ScanRunStatus.RUNNING,
        trigger="manual",
        commit_sha=None,
        ref=None,
        created_at=now,
        started_at=None,
        completed_at=None,
    )


class _SessionSpy:
    """Stand-in for `get_session()` — records enter/exit and how many times
    it was constructed, without touching a real database."""

    instances: list[_SessionSpy] = []

    def __init__(self) -> None:
        self.entered = False
        self.exited = False
        _SessionSpy.instances.append(self)

    def __call__(self) -> _SessionSpy:
        return self

    async def __aenter__(self) -> object:
        self.entered = True
        return object()

    async def __aexit__(self, *_exc_info: object) -> None:
        self.exited = True


class _ExplodingSessionSpy:
    """A `get_session()` stand-in that fails the test if ever entered — the
    zero-DB-query proof for the 503 gate."""

    def __call__(self) -> _ExplodingSessionSpy:
        return self

    async def __aenter__(self) -> object:
        raise AssertionError("get_session() must not be called when realtime_enabled is False")

    async def __aexit__(self, *_exc_info: object) -> None:  # pragma: no cover
        return None


class _FakeScanRunRepository:
    def __init__(self, runs_by_id: dict[uuid.UUID, ScanRun]) -> None:
        self._runs_by_id = runs_by_id

    def __call__(self, _session: object) -> _FakeScanRunRepository:
        return self

    async def get_by_id(self, scan_run_id: uuid.UUID) -> ScanRun | None:
        return self._runs_by_id.get(scan_run_id)


class _FakeUserRepository:
    def __init__(self, users_by_id: dict[uuid.UUID, User]) -> None:
        self._users_by_id = users_by_id

    def __call__(self, _session: object) -> _FakeUserRepository:
        return self

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return self._users_by_id.get(user_id)


class _FakeRelay:
    """Stand-in for `ScanEventRelay`: `subscribe()` never touches Redis and
    hands back a queue the test pre-loads, so the streaming generator's
    single `queue.get()` resolves immediately."""

    def __init__(self, payloads: list[str] | None = None) -> None:
        self.subscribe_calls: list[str] = []
        self._payloads = payloads or []
        self.subscribed_after_session_closed: bool | None = None

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    @asynccontextmanager
    async def subscribe(self, scan_run_id: str) -> Any:
        self.subscribe_calls.append(scan_run_id)
        if _SessionSpy.instances:
            self.subscribed_after_session_closed = all(
                s.exited for s in _SessionSpy.instances
            )
        import asyncio

        queue: asyncio.Queue[str] = asyncio.Queue()
        for payload in self._payloads:
            queue.put_nowait(payload)
        yield queue


def _terminal_payload(scan_run_id: uuid.UUID) -> str:
    event = ScanStatusEvent(scan_run_id=scan_run_id, status=ScanRunStatus.COMPLETED, at="t")
    return event.to_json()


@pytest.fixture(autouse=True)
def _reset_session_spy() -> None:
    _SessionSpy.instances = []


def test_returns_503_and_makes_zero_db_calls_when_realtime_disabled(
    valid_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(scans_module, "get_session", _ExplodingSessionSpy())
    monkeypatch.setattr(auth_module, "get_session", _ExplodingSessionSpy())
    app = create_app()
    app.state.scan_event_relay = _FakeRelay()

    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/scans/{uuid.uuid4()}/events",
            headers={"Authorization": "Bearer not-a-real-token"},
        )

    assert response.status_code == 503


def test_returns_401_and_zero_subscribe_calls_for_a_bad_token(
    valid_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REALTIME_ENABLED", "true")
    monkeypatch.setattr(auth_module, "get_session", _SessionSpy())
    monkeypatch.setattr(auth_module, "SqlAlchemyUserRepository", _FakeUserRepository({}))
    app = create_app()
    relay = _FakeRelay()
    app.state.scan_event_relay = relay

    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/scans/{uuid.uuid4()}/events",
            headers={"Authorization": "Bearer not-a-jwt"},
        )

    assert response.status_code == 401
    assert relay.subscribe_calls == []


def test_returns_404_and_zero_subscribe_calls_for_an_unknown_scan_run(
    valid_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REALTIME_ENABLED", "true")
    user = _make_user()
    monkeypatch.setattr(auth_module, "get_session", _SessionSpy())
    monkeypatch.setattr(
        auth_module, "SqlAlchemyUserRepository", _FakeUserRepository({user.id: user})
    )
    monkeypatch.setattr(scans_module, "get_session", _SessionSpy())
    monkeypatch.setattr(
        scans_module, "SqlAlchemyScanRunRepository", _FakeScanRunRepository({})
    )
    app = create_app()
    relay = _FakeRelay()
    app.state.scan_event_relay = relay
    token = create_access_token(user)

    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/scans/{uuid.uuid4()}/events",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 404
    assert relay.subscribe_calls == []


def test_terminal_event_closes_the_stream(
    valid_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REALTIME_ENABLED", "true")
    user = _make_user()
    scan_run_id = uuid.uuid4()
    scan_run = _make_scan_run(scan_run_id)
    monkeypatch.setattr(auth_module, "get_session", _SessionSpy())
    monkeypatch.setattr(
        auth_module, "SqlAlchemyUserRepository", _FakeUserRepository({user.id: user})
    )
    monkeypatch.setattr(scans_module, "get_session", _SessionSpy())
    monkeypatch.setattr(
        scans_module, "SqlAlchemyScanRunRepository", _FakeScanRunRepository({scan_run_id: scan_run})
    )
    app = create_app()
    relay = _FakeRelay(payloads=[_terminal_payload(scan_run_id)])
    app.state.scan_event_relay = relay
    token = create_access_token(user)

    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/scans/{scan_run_id}/events",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: scan.status" in response.text
    assert relay.subscribe_calls == [str(scan_run_id)]


def test_no_pooled_session_is_held_while_streaming(
    valid_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Threat matrix — DB pool: the existence-check session must be closed
    BEFORE `relay.subscribe()` is entered — regression guard for the D-Auth
    session hazard."""
    monkeypatch.setenv("REALTIME_ENABLED", "true")
    user = _make_user()
    scan_run_id = uuid.uuid4()
    scan_run = _make_scan_run(scan_run_id)
    monkeypatch.setattr(auth_module, "get_session", _SessionSpy())
    monkeypatch.setattr(
        auth_module, "SqlAlchemyUserRepository", _FakeUserRepository({user.id: user})
    )
    monkeypatch.setattr(scans_module, "get_session", _SessionSpy())
    monkeypatch.setattr(
        scans_module, "SqlAlchemyScanRunRepository", _FakeScanRunRepository({scan_run_id: scan_run})
    )
    app = create_app()
    relay = _FakeRelay(payloads=[_terminal_payload(scan_run_id)])
    app.state.scan_event_relay = relay
    token = create_access_token(user)

    with TestClient(app) as client:
        client.get(
            f"/api/v1/scans/{scan_run_id}/events",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert relay.subscribed_after_session_closed is True
    assert all(s.exited for s in _SessionSpy.instances)


def test_header_token_authenticates_with_zero_query_param_present(
    valid_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Threat matrix — credential exposure: proves the query-string fallback
    is browser-only, never mandatory."""
    monkeypatch.setenv("REALTIME_ENABLED", "true")
    user = _make_user()
    scan_run_id = uuid.uuid4()
    scan_run = _make_scan_run(scan_run_id)
    monkeypatch.setattr(auth_module, "get_session", _SessionSpy())
    monkeypatch.setattr(
        auth_module, "SqlAlchemyUserRepository", _FakeUserRepository({user.id: user})
    )
    monkeypatch.setattr(scans_module, "get_session", _SessionSpy())
    monkeypatch.setattr(
        scans_module, "SqlAlchemyScanRunRepository", _FakeScanRunRepository({scan_run_id: scan_run})
    )
    app = create_app()
    relay = _FakeRelay(payloads=[_terminal_payload(scan_run_id)])
    app.state.scan_event_relay = relay
    token = create_access_token(user)

    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/scans/{scan_run_id}/events",  # no ?access_token=...
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200


def test_stream_authz_matches_get_scan_endpoint_parity(
    valid_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Threat matrix — cross-tenant leakage: same authenticated-only policy
    (member-or-admin, no per-scan check) as `GET /scans/{id}` — no new
    exposure, also no new protection (proposal assumption 2)."""
    monkeypatch.setenv("REALTIME_ENABLED", "true")
    monkeypatch.setattr(auth_module, "get_session", _SessionSpy())
    monkeypatch.setattr(auth_module, "SqlAlchemyUserRepository", _FakeUserRepository({}))
    app = create_app()
    app.state.scan_event_relay = _FakeRelay()

    with TestClient(app) as client:
        events_response = client.get(
            f"/api/v1/scans/{uuid.uuid4()}/events",
            headers={"Authorization": "Bearer garbage"},
        )
        detail_response = client.get(
            f"/api/v1/scans/{uuid.uuid4()}", headers={"Authorization": "Bearer garbage"}
        )

    assert events_response.status_code == detail_response.status_code == 401
