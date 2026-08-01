"""SQLAlchemy ORM models for the core aggregates."""

from __future__ import annotations

from orchestrator.infrastructure.db.models.api_key import ApiKeyModel
from orchestrator.infrastructure.db.models.code_repository import CodeRepositoryModel
from orchestrator.infrastructure.db.models.credential_access_log import CredentialAccessLogModel
from orchestrator.infrastructure.db.models.finding import FindingModel
from orchestrator.infrastructure.db.models.github_check_publication import (
    GitHubCheckPublicationModel,
)
from orchestrator.infrastructure.db.models.github_repository_installation import (
    GitHubRepositoryInstallationModel,
)
from orchestrator.infrastructure.db.models.scan_run import ScanRunModel
from orchestrator.infrastructure.db.models.scan_target import ScanTargetModel
from orchestrator.infrastructure.db.models.scan_task import ScanTaskModel
from orchestrator.infrastructure.db.models.user import UserModel
from orchestrator.infrastructure.db.models.webhook_delivery import WebhookDeliveryModel

__all__ = [
    "ApiKeyModel",
    "CodeRepositoryModel",
    "CredentialAccessLogModel",
    "FindingModel",
    "GitHubCheckPublicationModel",
    "GitHubRepositoryInstallationModel",
    "ScanRunModel",
    "ScanTargetModel",
    "ScanTaskModel",
    "UserModel",
    "WebhookDeliveryModel",
]
