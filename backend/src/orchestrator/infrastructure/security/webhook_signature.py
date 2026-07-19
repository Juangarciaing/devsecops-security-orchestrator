"""GitHub webhook HMAC-SHA256 signature verification (design D2).

Pure function, NEVER raises: an unset secret, missing header, or malformed
header all resolve to `False` rather than an exception (D1 fail-closed —
the caller treats `False` as "reject and audit", not "error"). Comparison
is constant-time (`hmac.compare_digest`) to avoid timing side-channels.
"""

from __future__ import annotations

import hashlib
import hmac

_SIGNATURE_PREFIX = "sha256="


def verify_github_signature(
    secret: str | None, raw_body: bytes, signature_header: str | None
) -> bool:
    """Verify `signature_header` (`X-Hub-Signature-256`) against `raw_body`.

    Returns `False` — never raises — when `secret` is unset, `signature_header`
    is missing, or `signature_header` does not carry the expected `sha256=`
    prefix.
    """
    if not secret or not signature_header:
        return False
    if not signature_header.startswith(_SIGNATURE_PREFIX):
        return False

    expected_digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    provided_digest = signature_header[len(_SIGNATURE_PREFIX) :]

    return hmac.compare_digest(expected_digest, provided_digest)
