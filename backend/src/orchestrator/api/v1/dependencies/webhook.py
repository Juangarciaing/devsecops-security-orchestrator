"""`verify_webhook_signature` — DI wrapper for GitHub webhook HMAC checks (design D2).

Reads `await request.body()` (Starlette caches the raw bytes internally, so a
downstream `GitHubPushPayload` JSON parse in PR3's use case still works off
the same cached body) and delegates the actual HMAC comparison to the pure
`verify_github_signature`. No DB access, no raise — PR3's router/use case
decides how to respond to an invalid signature (D3/D4).
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from orchestrator.infrastructure.config.settings import get_settings
from orchestrator.infrastructure.security.webhook_signature import verify_github_signature

_SIGNATURE_HEADER = "X-Hub-Signature-256"


@dataclass(slots=True, frozen=True)
class SignatureCheck:
    """Result of verifying an inbound webhook request's signature."""

    raw_body: bytes
    valid: bool


async def verify_webhook_signature(request: Request) -> SignatureCheck:
    """Read the raw request body and verify its `X-Hub-Signature-256` header."""
    raw_body = await request.body()
    settings = get_settings()
    signature_header = request.headers.get(_SIGNATURE_HEADER)
    valid = verify_github_signature(settings.github_webhook_secret, raw_body, signature_header)
    return SignatureCheck(raw_body=raw_body, valid=valid)
