"""`WebhookDeliveryPort` — persistence contract for `WebhookDelivery`.

Framework-free: this module MUST NOT import SQLAlchemy. Typed with domain
entities/value objects only.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from orchestrator.domain.entities.webhook_delivery import WebhookDelivery


class WebhookDeliveryPort(ABC):
    """Async persistence contract for the append-only `WebhookDelivery` audit log."""

    @abstractmethod
    async def exists(self, delivery_id: str) -> bool:
        """Return whether a delivery with this `delivery_id` was already recorded.

        Only ever consulted for signature-valid deliveries (design D-data-model):
        `delivery_id` is nullable and repeated rejected/header-less deliveries
        never populate it, so replay detection is scoped to genuine GitHub
        redeliveries of a verified request.
        """

    @abstractmethod
    async def record(self, delivery: WebhookDelivery) -> None:
        """Persist `delivery` as a new append-only audit row."""
