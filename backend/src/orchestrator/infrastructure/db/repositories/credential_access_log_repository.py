"""`SqlAlchemyCredentialAccessLogRepository` — concrete `CredentialAccessLogPort`
adapter, following the same pattern established by `SqlAlchemyWebhookDeliveryRepository`.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.domain.entities.credential_access_log import CredentialAccessLog
from orchestrator.domain.ports.credential_access_log_port import CredentialAccessLogPort
from orchestrator.infrastructure.db.mappers import credential_access_log_to_model


class SqlAlchemyCredentialAccessLogRepository(CredentialAccessLogPort):
    """`CredentialAccessLogPort` adapter backed by a SQLAlchemy `AsyncSession`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, entry: CredentialAccessLog) -> None:
        model = credential_access_log_to_model(entry)
        self._session.add(model)
        await self._session.flush()
