"""`CredentialAccessLogPort` — persistence contract for `CredentialAccessLog`.

Framework-free: this module MUST NOT import SQLAlchemy. Typed with domain
entities/value objects only. Mirrors `WebhookDeliveryPort`'s shape.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from orchestrator.domain.entities.credential_access_log import CredentialAccessLog


class CredentialAccessLogPort(ABC):
    """Async persistence contract for the append-only `CredentialAccessLog` audit log.

    Not yet wired to any writer in this PR (persistence layer only) — the
    worker-side unseal-and-audit flow that calls `append()` lands in a later
    PR (design D9).
    """

    @abstractmethod
    async def append(self, entry: CredentialAccessLog) -> None:
        """Persist `entry` as a new append-only audit row."""
