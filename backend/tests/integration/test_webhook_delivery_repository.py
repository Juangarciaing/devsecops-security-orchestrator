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


async def _list_recent_orders_newest_first_by_received_at_then_id() -> None:
    """design D9: `ORDER BY received_at DESC, id DESC` — two rows sharing the
    exact same `received_at` must still resolve deterministically by `id`."""
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        tie_time = datetime(2025, 6, 1, 12, 0, 0)
        older = WebhookDelivery(
            id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            signature_valid=True,
            outcome=WebhookOutcome.ACCEPTED,
            received_at=datetime(2025, 1, 1),
            delivery_id=f"delivery-order-old-{uuid.uuid4()}",
        )
        tie_low_id = WebhookDelivery(
            id=uuid.UUID("00000000-0000-0000-0000-000000000010"),
            signature_valid=True,
            outcome=WebhookOutcome.ACCEPTED,
            received_at=tie_time,
            delivery_id=f"delivery-order-tie-low-{uuid.uuid4()}",
        )
        tie_high_id = WebhookDelivery(
            id=uuid.UUID("00000000-0000-0000-0000-000000000020"),
            signature_valid=True,
            outcome=WebhookOutcome.ACCEPTED,
            received_at=tie_time,
            delivery_id=f"delivery-order-tie-high-{uuid.uuid4()}",
        )

        async with sessionmaker() as session:
            repository = SqlAlchemyWebhookDeliveryRepository(session)
            for delivery in (older, tie_low_id, tie_high_id):
                await repository.record(delivery)
            await session.commit()

        async with sessionmaker() as session:
            repository = SqlAlchemyWebhookDeliveryRepository(session)
            result = await repository.list_recent(limit=100, offset=0)

        result_ids = [row.id for row in result]
        # Both tie-broken rows sort before the older row, and within the tie,
        # the higher id sorts first — proves `id DESC` is a real tiebreaker,
        # not incidental insertion order.
        assert result_ids.index(tie_high_id.id) < result_ids.index(tie_low_id.id)
        assert result_ids.index(tie_low_id.id) < result_ids.index(older.id)
    finally:
        await engine.dispose()


def test_list_recent_orders_newest_first_by_received_at_then_id(migrated_schema: None) -> None:
    asyncio.run(_list_recent_orders_newest_first_by_received_at_then_id())


async def _list_recent_paginates_without_row_reappearing_on_next_page() -> None:
    engine = create_async_engine(resolve_database_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        deliveries = [
            WebhookDelivery(
                id=uuid.uuid4(),
                signature_valid=True,
                outcome=WebhookOutcome.ACCEPTED,
                received_at=datetime(2025, 3, 1, 0, 0, i),
                delivery_id=f"delivery-page-{i}-{uuid.uuid4()}",
            )
            for i in range(5)
        ]

        async with sessionmaker() as session:
            repository = SqlAlchemyWebhookDeliveryRepository(session)
            for delivery in deliveries:
                await repository.record(delivery)
            await session.commit()

        async with sessionmaker() as session:
            repository = SqlAlchemyWebhookDeliveryRepository(session)
            page_one = await repository.list_recent(limit=3, offset=0)
            page_two = await repository.list_recent(limit=3, offset=3)

        page_one_ids = {row.id for row in page_one}
        page_two_ids = {row.id for row in page_two}

        assert len(page_one) == 3
        # No row from page 1 reappears on page 2.
        assert page_one_ids.isdisjoint(page_two_ids)
    finally:
        await engine.dispose()


def test_list_recent_pagination_no_row_reappears_on_next_page(migrated_schema: None) -> None:
    asyncio.run(_list_recent_paginates_without_row_reappearing_on_next_page())
