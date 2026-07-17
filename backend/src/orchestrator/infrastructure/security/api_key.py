"""API-key generation/hashing (D2: SHA-256 for high-entropy secrets, not argon2).

Format `dso_<prefix8>.<secret43>`: `key_prefix` (`dso_<prefix8>`) is a
non-secret unique lookup id; the secret half is hashed with SHA-256 and only
the hash is ever stored. The full `raw_key` is returned once, at creation, and
is never persisted or logged. Issuance/revocation only — request-time
API-key *verification* as an auth method is out of this module's scope.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

_PREFIX_LABEL = "dso_"
_PREFIX_BYTES = 6  # token_urlsafe(6) -> 8 base64url chars, no padding
_SECRET_BYTES = 32  # token_urlsafe(32) -> 43 base64url chars, no padding


@dataclass(slots=True, frozen=True)
class GeneratedApiKey:
    """Result of generating a new API key: the one-time plaintext plus its stored parts."""

    raw_key: str
    key_prefix: str
    hashed_key: str


def hash_api_key_secret(secret: str) -> str:
    """Hash the secret half of an API key with SHA-256. Never reversible."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def generate_api_key() -> GeneratedApiKey:
    """Generate a new high-entropy API key, split into `key_prefix` + `hashed_key`."""
    prefix = secrets.token_urlsafe(_PREFIX_BYTES)
    secret = secrets.token_urlsafe(_SECRET_BYTES)
    key_prefix = f"{_PREFIX_LABEL}{prefix}"
    raw_key = f"{key_prefix}.{secret}"
    return GeneratedApiKey(
        raw_key=raw_key,
        key_prefix=key_prefix,
        hashed_key=hash_api_key_secret(secret),
    )
