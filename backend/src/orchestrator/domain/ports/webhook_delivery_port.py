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

    @abstractmethod
    async def list_recent(self, limit: int, offset: int) -> list[WebhookDelivery]:
        """Return up to `limit` `WebhookDelivery` rows, skipping `offset`,
        ordered newest-first (design D9: `received_at DESC, id DESC` — the
        append-only table has no other unique time ordering).

        Powers the admin-gated `GET /api/v1/webhooks/deliveries` read path
        (design D8: `limit`/`offset` query params, defaults 20/0, `le=100`).
        """
