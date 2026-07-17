"""`issue_api_key` use case — pairs task 3.4's `generate_api_key` with `ApiKeyPort`."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime

from orchestrator.application.use_cases.issue_api_key import issue_api_key
from orchestrator.domain.entities.api_key import ApiKey
from orchestrator.domain.ports.api_key_port import ApiKeyPort


class _FakeApiKeyRepository(ApiKeyPort):
    def __init__(self) -> None:
        self.created: list[ApiKey] = []

    async def create(self, api_key: ApiKey) -> ApiKey:
        self.created.append(api_key)
        return api_key

    async def get_by_prefix(self, key_prefix: str) -> ApiKey | None:
        raise NotImplementedError

    async def list_for_user(self, user_id: uuid.UUID) -> list[ApiKey]:
        raise NotImplementedError

    async def revoke(self, key_id: uuid.UUID) -> ApiKey:
        raise NotImplementedError

    async def touch(self, key_id: uuid.UUID) -> ApiKey:
        raise NotImplementedError


def test_issue_api_key_returns_entity_and_the_one_time_raw_key() -> None:
    repository = _FakeApiKeyRepository()
    user_id = uuid.uuid4()

    created, raw_key = asyncio.run(issue_api_key(repository, user_id))

    assert created.user_id == user_id
    assert raw_key.startswith(created.key_prefix + ".")
    assert repository.created == [created]


def test_issue_api_key_stores_only_the_hash_never_the_raw_secret() -> None:
    repository = _FakeApiKeyRepository()

    created, raw_key = asyncio.run(issue_api_key(repository, uuid.uuid4()))
    _, _, secret = raw_key.partition(".")

    assert created.hashed_key == hashlib.sha256(secret.encode("utf-8")).hexdigest()
    assert secret not in created.hashed_key


def test_issue_api_key_new_keys_are_active_and_have_no_created_at_in_the_future_naive() -> None:
    repository = _FakeApiKeyRepository()

    created, _ = asyncio.run(issue_api_key(repository, uuid.uuid4()))

    assert created.is_active is True
    assert created.created_at <= datetime.now(UTC).replace(tzinfo=None)
