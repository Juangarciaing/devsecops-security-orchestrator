"""`classify_publish_failure` (PR6, design: "Retry classification").

Pure function — no DB, no Celery, no real network. Confirms the wrapper
around `GitHubChecksHttpClient.publish()` never re-implements/duplicates
PR5c's own internal one-shot 401 refresh; it only classifies whatever
`publish()` ultimately raises.
"""

from __future__ import annotations

import random

import httpx
import pytest

from orchestrator.workers.github_checks_retry import (
    MAX_ATTEMPTS,
    MAX_DELAY_SECONDS,
    MIN_DELAY_SECONDS,
    classify_publish_failure,
)


def _status_error(status: int, headers: dict[str, str] | None = None) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.github.com/repos/acme/widgets/check-runs")
    response = httpx.Response(status, headers=headers or {}, request=request)
    return httpx.HTTPStatusError(f"status {status}", request=request, response=response)


def test_429_honors_retry_after_header() -> None:
    exc = _status_error(429, headers={"Retry-After": "45"})

    decision = classify_publish_failure(exc, attempt_count=1)

    assert decision.should_retry is True
    assert decision.delay_seconds == 45.0


def test_429_falls_back_to_rate_limit_reset_header_when_no_retry_after() -> None:
    import time

    reset_epoch = time.time() + 90
    exc = _status_error(429, headers={"X-RateLimit-Reset": str(reset_epoch)})

    decision = classify_publish_failure(exc, attempt_count=1)

    assert decision.should_retry is True
    assert decision.delay_seconds is not None
    assert 80.0 <= decision.delay_seconds <= 100.0


@pytest.mark.parametrize("attempt_count", list(range(1, MAX_ATTEMPTS)))
def test_5xx_and_timeout_retry_within_jitter_bounds(attempt_count: int) -> None:
    """`MAX_ATTEMPTS` itself is exhaustion, not a retryable attempt — see
    `test_attempt_exhaustion_is_dead_even_for_an_otherwise_retryable_failure`."""
    for exc in (
        _status_error(503),
        httpx.TimeoutException("timed out"),
        httpx.ConnectError("connection reset"),
    ):
        decision = classify_publish_failure(exc, attempt_count=attempt_count, rng=random.Random(0))
        assert decision.should_retry is True
        assert MIN_DELAY_SECONDS <= decision.delay_seconds <= MAX_DELAY_SECONDS  # type: ignore[operator]


def test_401_403_404_retry_without_a_second_internal_refresh() -> None:
    """`publish()` already spent its ONE internal refresh/remap retry on
    these statuses (PR5c) — an escaped occurrence here is classified like
    any other retryable failure, never given a second internal loop by this
    classifier (it only returns a decision; it never calls `publish()`
    itself)."""
    for status in (401, 403, 404):
        decision = classify_publish_failure(_status_error(status), attempt_count=1)
        assert decision.should_retry is True


@pytest.mark.parametrize("status", [400, 405, 409, 410, 422])
def test_terminal_4xx_is_dead_immediately_regardless_of_attempt_count(status: int) -> None:
    decision = classify_publish_failure(_status_error(status), attempt_count=1)

    assert decision.should_retry is False
    assert decision.dead_letter_reason == f"http_{status}"


def test_attempt_exhaustion_is_dead_even_for_an_otherwise_retryable_failure() -> None:
    decision = classify_publish_failure(_status_error(503), attempt_count=MAX_ATTEMPTS)

    assert decision.should_retry is False
    assert decision.dead_letter_reason == "attempts_exhausted"


def test_an_unclassified_exception_is_dead_not_silently_retried_forever() -> None:
    decision = classify_publish_failure(RuntimeError("boom"), attempt_count=1)

    assert decision.should_retry is False
    assert decision.dead_letter_reason == "unclassified_error"


def test_delay_grows_with_attempt_count_before_hitting_the_cap() -> None:
    early = classify_publish_failure(_status_error(503), attempt_count=1, rng=random.Random(1))
    late = classify_publish_failure(_status_error(503), attempt_count=8, rng=random.Random(1))

    assert early.delay_seconds == MIN_DELAY_SECONDS  # attempt 1's window is exactly [30, 30]
    assert late.delay_seconds is not None
    assert late.delay_seconds > early.delay_seconds
