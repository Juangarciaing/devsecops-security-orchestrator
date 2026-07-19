"""Contract tests for `SqlAlchemyWebhookDeliveryRepository` against a live
Postgres.

DDL-level constraints are proven in `test_migration_add_webhook_deliveries.py`;
this file proves the repository adapter correctly implements
`WebhookDeliveryPort` — `record` persists every outcome (including rejected/
header-less deliveries with a `None` `delivery_id`), `exists` finds a known
`delivery_id`, and repeated `None` `delivery_id` rows never violate the
`UNIQUE(delivery_id)` constraint (Postgres allows arbitrarily many `NULL`s).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestrator.domain.entities.webhook_delivery import WebhookDelivery
from orchestrator.domain.value_objects.enums import WebhookOutcome
from orchestrator.infrastructure.db.engine import resolve_database_url
from orchestrator.infrastructure.db.repositories.webhook_delivery_repository import (
    SqlAlchemyWebhookDeliveryRepository,
)

pytestmark = pytest.mark.integration

_NOW = datetime.now(UTC).replace(tzinfo=None)


async def _record_and_check_exists() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        delivery_id = f"delivery-{uuid.uuid4()}"

        async with sessionmaker() as session:
            repository = SqlAlchemyWebhookDeliveryRepository(session)

            missing = await repository.exists(delivery_id)
            assert missing is False

            await repository.record(
                WebhookDelivery(
                    id=uuid.uuid4(),
                    signature_valid=True,
                    outcome=WebhookOutcome.ACCEPTED,
                    received_at=_NOW,
                    delivery_id=delivery_id,
                    event_type="push",
                    source_ip="203.0.113.5",
                    repository_full_name="acme/widgets",
                    ref="refs/heads/main",
                    commit_sha="d" * 40,
                )
            )
            await session.commit()

        async with sessionmaker() as session:
            repository = SqlAlchemyWebhookDeliveryRepository(session)

            present = await repository.exists(delivery_id)
            assert present is True
    finally:
        await engine.dispose()


def test_record_persists_and_exists_finds_a_known_delivery_id(migrated_schema: None) -> None:
    asyncio.run(_record_and_check_exists())


async def _repeated_null_delivery_ids_never_violate_unique() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            repository = SqlAlchemyWebhookDeliveryRepository(session)

            for _ in range(3):
                await repository.record(
                    WebhookDelivery(
                        id=uuid.uuid4(),
                        signature_valid=False,
                        outcome=WebhookOutcome.REJECTED_SIGNATURE,
                        received_at=_NOW,
                        delivery_id=None,
                        event_type=None,
                        source_ip="203.0.113.5",
                        repository_full_name=None,
                        ref=None,
                        commit_sha=None,
                    )
                )
            # No IntegrityError — three NULL `delivery_id` rows coexist under
            # `UNIQUE(delivery_id)`.
            await session.commit()
    finally:
        await engine.dispose()


def test_repeated_null_delivery_id_rows_never_violate_unique_constraint(
    migrated_schema: None,
) -> None:
    asyncio.run(_repeated_null_delivery_ids_never_violate_unique())


async def _exists_returns_false_for_unknown_delivery_id() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            repository = SqlAlchemyWebhookDeliveryRepository(session)

            result = await repository.exists("never-recorded")
            assert result is False
    finally:
        await engine.dispose()


def test_exists_returns_false_for_unknown_delivery_id(migrated_schema: None) -> None:
    asyncio.run(_exists_returns_false_for_unknown_delivery_id())
