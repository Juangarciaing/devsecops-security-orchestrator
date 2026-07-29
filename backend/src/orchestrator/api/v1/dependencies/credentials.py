"""`get_credential_store` — `Depends`-usable `CredentialStorePort` wired to `Settings`.

Mirrors `verify_webhook_signature` (`dependencies/webhook.py`) reading
`get_settings()` at call time rather than at import time, so tests that
`monkeypatch.setenv(...)` + `get_settings.cache_clear()` before a request
are picked up correctly.
"""

from __future__ import annotations

from orchestrator.domain.ports.credential_store_port import CredentialStorePort
from orchestrator.infrastructure.config.settings import get_settings
from orchestrator.infrastructure.security.credential_store import FernetCredentialStore


def get_credential_store() -> CredentialStorePort:
    """Build a `FernetCredentialStore` from `Settings.credential_encryption_key`.

    Constructed fresh per request — cheap, no I/O — mirroring
    `SqlAlchemyCodeRepositoryRepository(session)` being constructed inline in
    the repositories router rather than cached across requests.
    """
    settings = get_settings()
    return FernetCredentialStore(encryption_key=settings.credential_encryption_key)
