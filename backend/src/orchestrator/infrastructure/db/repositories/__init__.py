"""Concrete SQLAlchemy `*Port` adapters.

First concrete adapters in the project (Module 2 left this package empty,
shipping abstract `*Port` interfaces only).
"""

from __future__ import annotations

from orchestrator.infrastructure.db.repositories.api_key_repository import (
    SqlAlchemyApiKeyRepository,
)
from orchestrator.infrastructure.db.repositories.code_repository_repository import (
    CodeRepositoryNotFoundError,
    SqlAlchemyCodeRepositoryRepository,
)
from orchestrator.infrastructure.db.repositories.credential_access_log_repository import (
    SqlAlchemyCredentialAccessLogRepository,
)
from orchestrator.infrastructure.db.repositories.scan_target_repository import (
    ScanTargetNotFoundError,
    SqlAlchemyScanTargetRepository,
)
from orchestrator.infrastructure.db.repositories.user_repository import SqlAlchemyUserRepository
from orchestrator.infrastructure.db.repositories.webhook_delivery_repository import (
    SqlAlchemyWebhookDeliveryRepository,
)

__all__ = [
    "CodeRepositoryNotFoundError",
    "ScanTargetNotFoundError",
    "SqlAlchemyApiKeyRepository",
    "SqlAlchemyCodeRepositoryRepository",
    "SqlAlchemyCredentialAccessLogRepository",
    "SqlAlchemyScanTargetRepository",
    "SqlAlchemyUserRepository",
    "SqlAlchemyWebhookDeliveryRepository",
]
