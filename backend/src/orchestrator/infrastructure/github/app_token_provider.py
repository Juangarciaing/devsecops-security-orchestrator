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
from dataclasses import dataclass
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


def _app_headers(app_jwt: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {app_jwt}", "Accept": "application/vnd.github+json"}


class GitHubAppTokenProvider:
    """Mints short-lived GitHub App JWTs and caches installation access
    tokens in memory, keyed by installation id."""

    def __init__(
        self, *, app_id: str, private_key_file: str, http_client: httpx.AsyncClient
    ) -> None:
        self._app_id = app_id
        self._private_key_path = Path(private_key_file)
        self._http = http_client
        self._token_cache: dict[int, _CachedToken] = {}
        self._key_fingerprint: tuple[float, int] | None = None

    def _check_key_rotation(self) -> None:
        """Cheap `(mtime, size)` fingerprint check — called BEFORE any cache
        lookup (not only inside `_mint_app_jwt`), so a rotated key discards
        every cached installation token even on a call that would otherwise
        have been satisfied entirely from cache without ever minting a new
        JWT."""
        stat = self._private_key_path.stat()
        fingerprint = (stat.st_mtime, stat.st_size)
        if self._key_fingerprint is not None and fingerprint != self._key_fingerprint:
            self._token_cache.clear()
        self._key_fingerprint = fingerprint

    def _mint_app_jwt(self) -> str:
        """Re-reads the PEM from disk on every call (design: never cache PEM
        content) — a rotated key takes effect on the very next mint, no
        process restart required."""
        self._check_key_rotation()
        private_key_pem = self._private_key_path.read_bytes()
        now = int(time.time())
        payload = {"iss": self._app_id, "iat": now - 60, "exp": now + _APP_JWT_TTL_SECONDS}
        return jwt.encode(payload, private_key_pem, algorithm="RS256")

    async def get_installation_token(
        self, installation_id: int, *, force_refresh: bool = False
    ) -> str:
        """Cached in memory until `expires_at` minus a 5-minute skew (design:
        "Tokens"); `force_refresh` bypasses the cache (used by PR5c's single
        401 retry). The rotation check runs unconditionally BEFORE the cache
        lookup, not only on a cache miss."""
        self._check_key_rotation()
        cached = self._token_cache.get(installation_id)
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
        self._token_cache[installation_id] = _CachedToken(token=token, expires_at=expires_at)
        return token
