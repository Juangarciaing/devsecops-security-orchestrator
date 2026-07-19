"""`verify_github_signature` — HMAC-SHA256 constant-time verifier (design D2).

Pure function, never raises: computes `hmac.new(secret, raw_body,
sha256).hexdigest()` and compares against the `X-Hub-Signature-256` header
value (after stripping its `sha256=` prefix) via `hmac.compare_digest`.
Unset secret or missing/malformed header always yields `False` (D1
fail-closed) rather than raising.
"""

from __future__ import annotations

import hashlib
import hmac

from orchestrator.infrastructure.security.webhook_signature import verify_github_signature

_SECRET = "test-webhook-secret"
_BODY = b'{"ref": "refs/heads/main"}'


def _sign(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_verify_github_signature_accepts_a_correctly_signed_body() -> None:
    header = _sign(_SECRET, _BODY)

    assert verify_github_signature(_SECRET, _BODY, header) is True


def test_verify_github_signature_rejects_a_tampered_body() -> None:
    header = _sign(_SECRET, _BODY)
    tampered_body = b'{"ref": "refs/heads/evil"}'

    assert verify_github_signature(_SECRET, tampered_body, header) is False


def test_verify_github_signature_rejects_a_signature_from_the_wrong_secret() -> None:
    header = _sign("a-different-secret", _BODY)

    assert verify_github_signature(_SECRET, _BODY, header) is False


def test_verify_github_signature_rejects_a_missing_header() -> None:
    assert verify_github_signature(_SECRET, _BODY, None) is False


def test_verify_github_signature_rejects_an_unset_secret() -> None:
    header = _sign(_SECRET, _BODY)

    assert verify_github_signature(None, _BODY, header) is False


def test_verify_github_signature_rejects_a_header_without_the_sha256_prefix() -> None:
    digest = hmac.new(_SECRET.encode("utf-8"), _BODY, hashlib.sha256).hexdigest()

    assert verify_github_signature(_SECRET, _BODY, digest) is False


def test_verify_github_signature_never_raises_on_a_malformed_header() -> None:
    assert verify_github_signature(_SECRET, _BODY, "sha256=not-valid-hex-zzz") is False
