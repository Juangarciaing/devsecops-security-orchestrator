"""`GitHubAppTokenProvider` — App JWT minting + installation-token cache/
rotation (PR5b, design: "App credentials", "Tokens"). ALL HTTP is mocked via
`httpx.MockTransport`; the RSA keypair is generated locally per-test via
`cryptography` — NEVER a real GitHub App id/private key/installation id, and
NEVER a real network call to `api.github.com` (SECURITY constraint, PR5).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from orchestrator.infrastructure.github.app_token_provider import GitHubAppTokenProvider

_APP_ID = "654321"  # throwaway fixture value, not a real GitHub App id


def _generate_test_rsa_keypair() -> tuple[bytes, bytes]:
    """A locally-generated, throwaway 2048-bit RSA test keypair — NEVER a
    real GitHub App private key. Returns `(private_pem, public_pem)`."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


@pytest.fixture
def key_pair(tmp_path: Path) -> tuple[Path, bytes]:
    private_pem, public_pem = _generate_test_rsa_keypair()
    key_path = tmp_path / "test-app.pem"
    key_path.write_bytes(private_pem)
    return key_path, public_pem


def _provider(
    key_path: Path, handler: Callable[[httpx.Request], httpx.Response]
) -> GitHubAppTokenProvider:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(base_url="https://api.github.com", transport=transport)
    return GitHubAppTokenProvider(
        app_id=_APP_ID, private_key_file=str(key_path), http_client=http_client
    )


def _unreachable_handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
    raise AssertionError(f"unexpected HTTP call: {request.method} {request.url}")


def test_app_jwt_claims_are_signed_with_the_provided_key_and_verify_against_its_public_key(
    key_pair: tuple[Path, bytes],
) -> None:
    key_path, public_pem = key_pair
    provider = _provider(key_path, _unreachable_handler)

    token = provider._mint_app_jwt()  # noqa: SLF001 — testing the crypto contract directly

    decoded = jwt.decode(token, public_pem, algorithms=["RS256"], options={"verify_iat": False})
    assert decoded["iss"] == _APP_ID
    assert decoded["exp"] - decoded["iat"] <= 600  # GitHub's own 10-minute cap
    assert decoded["exp"] > decoded["iat"]


def _token_endpoint_handler(
    calls: list[str], *, expires_in: timedelta = timedelta(hours=1)
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        assert request.url.path == "/app/installations/42/access_tokens"
        expires_at = (datetime.now(UTC) + expires_in).isoformat().replace("+00:00", "Z")
        return httpx.Response(
            201, json={"token": "ghs_fake-installation-token", "expires_at": expires_at}
        )

    return handler


def test_mint_app_jwt_public_wrapper_returns_a_verifiable_token(
    key_pair: tuple[Path, bytes],
) -> None:
    key_path, public_pem = key_pair
    provider = _provider(key_path, _unreachable_handler)
    token = provider.mint_app_jwt()
    decoded = jwt.decode(token, public_pem, algorithms=["RS256"], options={"verify_iat": False})
    assert decoded["iss"] == _APP_ID


def test_installation_token_is_fetched_once_and_cached_within_ttl(
    key_pair: tuple[Path, bytes],
) -> None:
    key_path, _ = key_pair
    calls: list[str] = []
    provider = _provider(key_path, _token_endpoint_handler(calls))

    async def _run() -> tuple[str, str]:
        first = await provider.get_installation_token(42)
        second = await provider.get_installation_token(42)
        return first, second

    first, second = asyncio.run(_run())

    assert first == second == "ghs_fake-installation-token"
    assert calls == ["POST /app/installations/42/access_tokens"]


def test_installation_token_refreshes_within_five_minutes_of_expiry(
    key_pair: tuple[Path, bytes],
) -> None:
    key_path, _ = key_pair
    calls: list[str] = []
    provider = _provider(key_path, _token_endpoint_handler(calls, expires_in=timedelta(minutes=2)))

    async def _run() -> None:
        await provider.get_installation_token(42)
        await provider.get_installation_token(42)

    asyncio.run(_run())

    assert calls == [
        "POST /app/installations/42/access_tokens",
        "POST /app/installations/42/access_tokens",
    ]


def test_force_refresh_bypasses_a_still_valid_cached_token(
    key_pair: tuple[Path, bytes],
) -> None:
    key_path, _ = key_pair
    calls: list[str] = []
    provider = _provider(key_path, _token_endpoint_handler(calls))

    async def _run() -> None:
        await provider.get_installation_token(42)
        await provider.get_installation_token(42, force_refresh=True)

    asyncio.run(_run())

    assert calls == [
        "POST /app/installations/42/access_tokens",
        "POST /app/installations/42/access_tokens",
    ]


def test_key_rotation_invalidates_the_cached_token_and_mints_with_the_new_key(
    key_pair: tuple[Path, bytes], tmp_path: Path
) -> None:
    """Design: "App credentials" — a rotated key file takes effect on the
    very next mint (no process restart), and the stale cached installation
    token is discarded rather than kept alive under the old key's authority."""
    key_path, _first_public_pem = key_pair
    _second_private_pem, second_public_pem = _generate_test_rsa_keypair()
    calls: list[str] = []
    minted_jwts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        minted_jwts.append(request.headers["Authorization"].removeprefix("Bearer "))
        expires_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        return httpx.Response(
            201, json={"token": "ghs_fake-installation-token", "expires_at": expires_at}
        )

    provider = _provider(key_path, handler)

    async def _run() -> None:
        await provider.get_installation_token(42)

    asyncio.run(_run())
    assert len(calls) == 1

    # Rotate the key file on disk — new content, mtime bumped forward.
    key_path.write_bytes(_second_private_pem)
    later = datetime.now().timestamp() + 5
    os.utime(key_path, (later, later))

    asyncio.run(_run())

    assert len(calls) == 2  # cache was discarded, so the token was re-fetched
    # The second mint used the ROTATED key — decodable only with its public half.
    jwt.decode(
        minted_jwts[1], second_public_pem, algorithms=["RS256"], options={"verify_iat": False}
    )
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(
            minted_jwts[1], _first_public_pem, algorithms=["RS256"], options={"verify_iat": False}
        )


def test_key_rotation_is_detected_even_on_a_call_served_entirely_from_cache(
    key_pair: tuple[Path, bytes],
) -> None:
    """Regression guard for the exact ordering bug PR5's original RED test
    caught: the cache short-circuit must never run before the rotation
    fingerprint check, or a rotated key would silently leave a stale token
    cached indefinitely on a call that would otherwise be servable from
    cache alone."""
    key_path, _first_public_pem = key_pair
    second_private_pem, _second_public_pem = _generate_test_rsa_keypair()
    calls: list[str] = []
    provider = _provider(key_path, _token_endpoint_handler(calls, expires_in=timedelta(hours=1)))

    async def _run() -> None:
        await provider.get_installation_token(42)

    asyncio.run(_run())
    assert len(calls) == 1  # cached — a second call within TTL would normally not re-fetch

    key_path.write_bytes(second_private_pem)
    later = datetime.now().timestamp() + 5
    os.utime(key_path, (later, later))

    asyncio.run(_run())

    assert len(calls) == 2  # rotation was still detected despite an otherwise-cacheable call
