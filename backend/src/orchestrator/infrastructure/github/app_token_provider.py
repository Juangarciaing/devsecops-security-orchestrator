"""`GitHubAppTokenProvider` — App JWT minting + installation-token cache and
rotation (PR5b, design: "App credentials", "Tokens"). Only the worker
process constructs this; Beat never reads the PEM (design constraint).

PR5b scope only: JWT minting and installation-token acquisition/caching. It
does NOT resolve installation mappings and does NOT implement any Check
Run lookup/publish behavior — that composition happens in PR5c's
`GitHubChecksHttpClient`, which imports this class for token acquisition
only. This class implements no port itself; it is a plain, reusable
infrastructure helper.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import jwt

_APP_JWT_TTL_SECONDS = 540  # 9 minutes — under GitHub's own 10-minute cap
_TOKEN_REFRESH_SKEW = timedelta(minutes=5)


@dataclass(slots=True, frozen=True)
class _CachedToken:
    token: str
    expires_at: datetime


@dataclass(slots=True)
class AppTokenCache:
    """Plain-data cache state, injectable so it can be SHARED across
    `GitHubAppTokenProvider` instances that are otherwise recreated on every
    call (each Celery sweep invocation gets a fresh `httpx.AsyncClient` bound
    to a fresh event loop — see `workers/db.run_async` — but this cache holds
    no loop-bound resources, so a caller MAY keep one instance alive for the
    lifetime of a worker process and inject it into every fresh provider,
    turning ~55 minutes of would-be re-mints into one real mint). Both the
    token cache AND the rotation fingerprint must travel together: injecting
    only the token cache while leaving the fingerprint to reset every call
    would silently defeat rotation detection (a provider that has never seen
    a fingerprint treats any cached token as still valid, never comparing it
    against the CURRENT on-disk key)."""

    tokens: dict[int, _CachedToken] = field(default_factory=dict)
    key_fingerprint: tuple[float, int] | None = None


def _app_headers(app_jwt: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {app_jwt}", "Accept": "application/vnd.github+json"}


class GitHubAppTokenProvider:
    """Mints short-lived GitHub App JWTs and caches installation access
    tokens in memory, keyed by installation id."""

    def __init__(
        self,
        *,
        app_id: str,
        private_key_file: str,
        http_client: httpx.AsyncClient,
        cache: AppTokenCache | None = None,
    ) -> None:
        self._app_id = app_id
        self._private_key_path = Path(private_key_file)
        self._http = http_client
        #: Defaults to a fresh, isolated cache (existing single-instance
        #: behavior, unchanged) unless a caller explicitly injects a shared
        #: one to persist across instances.
        self._cache = cache if cache is not None else AppTokenCache()

    def _check_key_rotation(self) -> None:
        """Cheap `(mtime, size)` fingerprint check — called BEFORE any cache
        lookup (not only inside `_mint_app_jwt`), so a rotated key discards
        every cached installation token even on a call that would otherwise
        have been satisfied entirely from cache without ever minting a new
        JWT."""
        stat = self._private_key_path.stat()
        fingerprint = (stat.st_mtime, stat.st_size)
        if self._cache.key_fingerprint is not None and fingerprint != self._cache.key_fingerprint:
            self._cache.tokens.clear()
        self._cache.key_fingerprint = fingerprint

    def _mint_app_jwt(self) -> str:
        """Re-reads the PEM from disk on every call (design: never cache PEM
        content) — a rotated key takes effect on the very next mint, no
        process restart required."""
        self._check_key_rotation()
        private_key_pem = self._private_key_path.read_bytes()
        now = int(time.time())
        payload = {"iss": self._app_id, "iat": now - 60, "exp": now + _APP_JWT_TTL_SECONDS}
        return jwt.encode(payload, private_key_pem, algorithm="RS256")

    def mint_app_jwt(self) -> str:
        """Public wrapper for PR5c's direct App-JWT mapping-discovery call."""
        return self._mint_app_jwt()

    async def get_installation_token(
        self, installation_id: int, *, force_refresh: bool = False
    ) -> str:
        """Cached in memory until `expires_at` minus a 5-minute skew (design:
        "Tokens"); `force_refresh` bypasses the cache (used by PR5c's single
        401 retry). The rotation check runs unconditionally BEFORE the cache
        lookup, not only on a cache miss."""
        self._check_key_rotation()
        cached = self._cache.tokens.get(installation_id)
        now = datetime.now(UTC)
        if (
            not force_refresh
            and cached is not None
            and cached.expires_at - _TOKEN_REFRESH_SKEW > now
        ):
            return cached.token
        app_jwt = self._mint_app_jwt()
        response = await self._http.post(
            f"/app/installations/{installation_id}/access_tokens",
            headers=_app_headers(app_jwt),
        )
        response.raise_for_status()
        body = response.json()
        token = str(body["token"])
        expires_at = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00")).replace(
            tzinfo=UTC
        )
        self._cache.tokens[installation_id] = _CachedToken(token=token, expires_at=expires_at)
        return token
