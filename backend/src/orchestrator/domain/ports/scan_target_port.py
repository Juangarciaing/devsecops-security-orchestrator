"""`ScanTargetPort` — persistence contract for `ScanTarget`.

Framework-free: this module MUST NOT import SQLAlchemy. Typed with domain
entities only.

Mirrors `CodeRepositoryPort`'s shape, minus git-identity lookups: `ScanTarget`
has no `(provider, owner, name)` concept, so `get_by_identity` is replaced by
`get_by_url` (design: "CodeRepositoryPort shape, get_by_identity→get_by_url").
There is no hard `delete` in this slice — nothing references a `ScanTarget`
yet (confirmed: independent entity, no linkage), and soft-delete is the
sanctioned deactivation path.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod

from orchestrator.domain.entities.scan_target import ScanTarget


class ScanTargetPort(ABC):
    """Async persistence contract for the `ScanTarget` aggregate."""

    @abstractmethod
    async def get_by_id(self, target_id: uuid.UUID) -> ScanTarget | None:
        """Return the `ScanTarget` with the given id, or `None` if absent."""

    @abstractmethod
    async def get_by_url(self, target_url: str) -> ScanTarget | None:
        """Return the `ScanTarget` matching `target_url`, or `None` if absent."""

    @abstractmethod
    async def list_all(self) -> list[ScanTarget]:
        """Return every tracked `ScanTarget`."""

    @abstractmethod
    async def list_active(self) -> list[ScanTarget]:
        """Return every `ScanTarget` with `is_active=True`."""

    @abstractmethod
    async def create(self, target: ScanTarget) -> ScanTarget:
        """Persist a new `ScanTarget` and return the stored entity."""

    @abstractmethod
    async def update(self, target: ScanTarget) -> ScanTarget:
        """Persist mutable-field changes for an existing `ScanTarget`.

        Raises `ScanTargetNotFoundError` (adapter-local) if `target.id` does
        not exist.
        """

    @abstractmethod
    async def soft_delete(self, target_id: uuid.UUID) -> None:
        """Set `is_active=False` for the given id. Idempotent: a no-op if the
        target is already inactive or does not exist."""
