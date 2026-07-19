"""`verify_webhook_signature` — DI wrapper reading raw body + secret (design D2).

Reads `await request.body()` (Starlette caches it, so a downstream JSON parse
in PR3's use case still works) and delegates to `verify_github_signature`. No
DB access, never raises — matches `test_auth.py`'s `asyncio.run(...)` pattern
(no `pytest-asyncio` plugin in this project).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac

import pytest
from starlette.requests import Request

import orchestrator.api.v1.dependencies.webhook as webhook_module
from orchestrator.api.v1.dependencies.webhook import verify_webhook_signature
from orchestrator.infrastructure.config.settings import Settings


def _make_request(body: bytes, headers: dict[str, str] | None = None) -> Request:
    encoded_headers = [
        (key.lower().encode(), value.encode()) for key, value in (headers or {}).items()
    ]
    scope = {"type": "http", "method": "POST", "headers": encoded_headers}
    sent = False

    async def receive() -> dict[str, object]:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


def _make_settings(secret: str | None) -> Settings:
    return Settings(
        database_url="postgresql://localhost/x",
        redis_url="redis://localhost",
        secret_key="s",
        jwt_secret_key="s",
        github_webhook_secret=secret,
    )


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _patch_settings(monkeypatch: pytest.MonkeyPatch, secret: str | None) -> None:
    monkeypatch.setattr(webhook_module, "get_settings", lambda: _make_settings(secret))


def test_verify_webhook_signature_returns_valid_true_for_a_correctly_signed_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b'{"ref": "refs/heads/main"}'
    _patch_settings(monkeypatch, "shh")
    request = _make_request(body, {"X-Hub-Signature-256": _sign("shh", body)})

    result = asyncio.run(verify_webhook_signature(request))

    assert result.raw_body == body
    assert result.valid is True


def test_verify_webhook_signature_returns_valid_false_for_a_wrong_secret_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b'{"ref": "refs/heads/main"}'
    _patch_settings(monkeypatch, "shh")
    request = _make_request(body, {"X-Hub-Signature-256": _sign("some-other-secret", body)})

    result = asyncio.run(verify_webhook_signature(request))

    assert result.raw_body == body
    assert result.valid is False


def test_verify_webhook_signature_reads_raw_body_even_when_secret_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b'{"ref": "refs/heads/main"}'
    _patch_settings(monkeypatch, None)
    request = _make_request(body, {"X-Hub-Signature-256": _sign("shh", body)})

    result = asyncio.run(verify_webhook_signature(request))

    assert result.raw_body == body
    assert result.valid is False


def test_verify_webhook_signature_reads_raw_body_even_when_header_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b'{"ref": "refs/heads/main"}'
    _patch_settings(monkeypatch, "shh")
    request = _make_request(body)

    result = asyncio.run(verify_webhook_signature(request))

    assert result.raw_body == body
    assert result.valid is False
