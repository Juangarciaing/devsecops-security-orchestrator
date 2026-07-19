"""Domain entity <-> ORM model conversion functions.

Keeps SQLAlchemy out of `domain/` — the domain layer never imports these
modules or the ORM models they reference. One `to_entity`/`to_model` pair per
aggregate.
"""

from __future__ import annotations

from orchestrator.domain.entities.api_key import ApiKey
from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.entities.scan_task import ScanTask
from orchestrator.domain.entities.user import User
from orchestrator.domain.entities.webhook_delivery import WebhookDelivery
from orchestrator.infrastructure.db.models.api_key import ApiKeyModel
from orchestrator.infrastructure.db.models.code_repository import CodeRepositoryModel
from orchestrator.infrastructure.db.models.finding import FindingModel
from orchestrator.infrastructure.db.models.scan_run import ScanRunModel
from orchestrator.infrastructure.db.models.scan_task import ScanTaskModel
from orchestrator.infrastructure.db.models.user import UserModel
from orchestrator.infrastructure.db.models.webhook_delivery import WebhookDeliveryModel


def code_repository_to_entity(model: CodeRepositoryModel) -> CodeRepository:
    """Convert a `CodeRepositoryModel` into a domain `CodeRepository` entity."""
    return CodeRepository(
        id=model.id,
        provider=model.provider,
        owner=model.owner,
        name=model.name,
        clone_url=model.clone_url,
        default_branch=model.default_branch,
        credential_ref=model.credential_ref,
        is_active=model.is_active,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def code_repository_to_model(entity: CodeRepository) -> CodeRepositoryModel:
    """Convert a domain `CodeRepository` entity into a `CodeRepositoryModel`."""
    return CodeRepositoryModel(
        id=entity.id,
        provider=entity.provider,
        owner=entity.owner,
        name=entity.name,
        clone_url=entity.clone_url,
        default_branch=entity.default_branch,
        credential_ref=entity.credential_ref,
        is_active=entity.is_active,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def scan_run_to_entity(model: ScanRunModel) -> ScanRun:
    """Convert a `ScanRunModel` into a domain `ScanRun` entity."""
    return ScanRun(
        id=model.id,
        repository_id=model.repository_id,
        status=model.status,
        trigger=model.trigger,
        commit_sha=model.commit_sha,
        ref=model.ref,
        created_at=model.created_at,
        started_at=model.started_at,
        completed_at=model.completed_at,
    )


def scan_run_to_model(entity: ScanRun) -> ScanRunModel:
    """Convert a domain `ScanRun` entity into a `ScanRunModel`."""
    return ScanRunModel(
        id=entity.id,
        repository_id=entity.repository_id,
        status=entity.status,
        trigger=entity.trigger,
        commit_sha=entity.commit_sha,
        ref=entity.ref,
        created_at=entity.created_at,
        started_at=entity.started_at,
        completed_at=entity.completed_at,
    )


def scan_task_to_entity(model: ScanTaskModel) -> ScanTask:
    """Convert a `ScanTaskModel` into a domain `ScanTask` entity."""
    return ScanTask(
        id=model.id,
        scan_run_id=model.scan_run_id,
        scanner_type=model.scanner_type,
        status=model.status,
        started_at=model.started_at,
        completed_at=model.completed_at,
        error_message=model.error_message,
    )


def scan_task_to_model(entity: ScanTask) -> ScanTaskModel:
    """Convert a domain `ScanTask` entity into a `ScanTaskModel`."""
    return ScanTaskModel(
        id=entity.id,
        scan_run_id=entity.scan_run_id,
        scanner_type=entity.scanner_type,
        status=entity.status,
        started_at=entity.started_at,
        completed_at=entity.completed_at,
        error_message=entity.error_message,
    )


def finding_to_entity(model: FindingModel) -> Finding:
    """Convert a `FindingModel` into a domain `Finding` entity."""
    return Finding(
        id=model.id,
        scan_task_id=model.scan_task_id,
        severity=model.severity,
        rule_id=model.rule_id,
        title=model.title,
        fingerprint=model.fingerprint,
        created_at=model.created_at,
        updated_at=model.updated_at,
        status=model.status,
        description=model.description,
        file_path=model.file_path,
        line_number=model.line_number,
        raw_evidence=model.raw_evidence,
        snippet=model.snippet,
        repository_id=model.repository_id,
        first_seen_scan_run_id=model.first_seen_scan_run_id,
        last_seen_scan_run_id=model.last_seen_scan_run_id,
    )


def finding_to_model(entity: Finding) -> FindingModel:
    """Convert a domain `Finding` entity into a `FindingModel`."""
    return FindingModel(
        id=entity.id,
        scan_task_id=entity.scan_task_id,
        severity=entity.severity,
        rule_id=entity.rule_id,
        title=entity.title,
        fingerprint=entity.fingerprint,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        status=entity.status,
        description=entity.description,
        file_path=entity.file_path,
        line_number=entity.line_number,
        raw_evidence=entity.raw_evidence,
        snippet=entity.snippet,
        repository_id=entity.repository_id,
        first_seen_scan_run_id=entity.first_seen_scan_run_id,
        last_seen_scan_run_id=entity.last_seen_scan_run_id,
    )


def user_to_entity(model: UserModel) -> User:
    """Convert a `UserModel` into a domain `User` entity."""
    return User(
        id=model.id,
        email=model.email,
        hashed_password=model.hashed_password,
        role=model.role,
        is_active=model.is_active,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def user_to_model(entity: User) -> UserModel:
    """Convert a domain `User` entity into a `UserModel`."""
    return UserModel(
        id=entity.id,
        email=entity.email,
        hashed_password=entity.hashed_password,
        role=entity.role,
        is_active=entity.is_active,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def api_key_to_entity(model: ApiKeyModel) -> ApiKey:
    """Convert an `ApiKeyModel` into a domain `ApiKey` entity."""
    return ApiKey(
        id=model.id,
        user_id=model.user_id,
        key_prefix=model.key_prefix,
        hashed_key=model.hashed_key,
        created_at=model.created_at,
        last_used_at=model.last_used_at,
        revoked_at=model.revoked_at,
    )


def api_key_to_model(entity: ApiKey) -> ApiKeyModel:
    """Convert a domain `ApiKey` entity into an `ApiKeyModel`."""
    return ApiKeyModel(
        id=entity.id,
        user_id=entity.user_id,
        key_prefix=entity.key_prefix,
        hashed_key=entity.hashed_key,
        created_at=entity.created_at,
        last_used_at=entity.last_used_at,
        revoked_at=entity.revoked_at,
    )


def webhook_delivery_to_entity(model: WebhookDeliveryModel) -> WebhookDelivery:
    """Convert a `WebhookDeliveryModel` into a domain `WebhookDelivery` entity."""
    return WebhookDelivery(
        id=model.id,
        signature_valid=model.signature_valid,
        outcome=model.outcome,
        received_at=model.received_at,
        delivery_id=model.delivery_id,
        event_type=model.event_type,
        source_ip=model.source_ip,
        repository_full_name=model.repository_full_name,
        ref=model.ref,
        commit_sha=model.commit_sha,
    )


def webhook_delivery_to_model(entity: WebhookDelivery) -> WebhookDeliveryModel:
    """Convert a domain `WebhookDelivery` entity into a `WebhookDeliveryModel`."""
    return WebhookDeliveryModel(
        id=entity.id,
        signature_valid=entity.signature_valid,
        outcome=entity.outcome,
        received_at=entity.received_at,
        delivery_id=entity.delivery_id,
        event_type=entity.event_type,
        source_ip=entity.source_ip,
        repository_full_name=entity.repository_full_name,
        ref=entity.ref,
        commit_sha=entity.commit_sha,
    )
