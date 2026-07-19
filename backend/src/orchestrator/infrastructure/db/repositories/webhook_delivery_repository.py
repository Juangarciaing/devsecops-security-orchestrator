"""`SqlAlchemyWebhookDeliveryRepository` — concrete `WebhookDeliveryPort`
adapter, following the same pattern established by `SqlAlchemyApiKeyRepository`.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.domain.entities.webhook_delivery import WebhookDelivery
from orchestrator.domain.ports.webhook_delivery_port import WebhookDeliveryPort
from orchestrator.infrastructure.db.mappers import webhook_delivery_to_model
from orchestrator.infrastructure.db.models.webhook_delivery import WebhookDeliveryModel


class SqlAlchemyWebhookDeliveryRepository(WebhookDeliveryPort):
    """`WebhookDeliveryPort` adapter backed by a SQLAlchemy `AsyncSession`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def exists(self, delivery_id: str) -> bool:
        stmt = select(WebhookDeliveryModel.id).where(
            WebhookDeliveryModel.delivery_id == delivery_id
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def record(self, delivery: WebhookDelivery) -> None:
        model = webhook_delivery_to_model(delivery)
        self._session.add(model)
        await self._session.flush()
