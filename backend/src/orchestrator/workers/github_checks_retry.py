"""`classify_publish_failure` — GitHub Checks delivery retry/backoff
classification (github-checks-publisher PR6, design: "Retry classification").

Wraps the CALLER's retry loop around `GitHubChecksHttpClient.publish()`
(PR5c) — `publish()`'s own internal one-shot 401/403/404 refresh/remap retry
is untouched and never duplicated here. An escaped 401/403/404 (meaning that
internal fix did not help) is classified like any other retryable failure;
each sweep-driven retry constructs a FRESH `publish()` call, which gets its
own one-shot internal fix, so no double-handling/looping ever happens here.

Framework-free: no Celery/Settings import (mirrors `workers/backoff.py`).
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

import httpx

#: Design: "up to 12 attempts". `attempt_count` passed in is 1-indexed and
#: includes the attempt that just failed.
MAX_ATTEMPTS = 12
#: Design: "full-jitter backoff between 30s and 1h".
MIN_DELAY_SECONDS = 30.0
MAX_DELAY_SECONDS = 3600.0

#: Statuses retried like a network/5xx blip. 401/403/404 are included
#: because `publish()` already spent its ONE internal refresh/remap retry on
#: them (see module docstring) — an escaped occurrence is not a second
#: internal loop, just an ordinary retryable outcome from this wrapper's
#: point of view.
_RETRYABLE_STATUSES = frozenset({401, 403, 404, 429})


@dataclass(frozen=True, slots=True)
class RetryDecision:
    """`should_retry=True` carries `delay_seconds`; `False` carries
    `dead_letter_reason`. Exactly one of the two is ever set."""

    should_retry: bool
    delay_seconds: float | None = None
    dead_letter_reason: str | None = None


def classify_publish_failure(
    exc: Exception,
    attempt_count: int,
    *,
    rng: random.Random | None = None,
) -> RetryDecision:
    """Classify one failed `publish()` attempt.

    `attempt_count` is the TOTAL number of attempts made so far, including
    the one that just failed (1-indexed) — exhausted at `MAX_ATTEMPTS`
    regardless of whether the underlying failure would otherwise be
    retryable (design: "Exhausting all 12 attempts -> DEAD").
    """
    reason = _terminal_reason(exc)
    if reason is not None:
        return RetryDecision(should_retry=False, dead_letter_reason=reason)
    if attempt_count >= MAX_ATTEMPTS:
        return RetryDecision(should_retry=False, dead_letter_reason="attempts_exhausted")
    return RetryDecision(should_retry=True, delay_seconds=_delay_seconds(exc, attempt_count, rng))


def _terminal_reason(exc: Exception) -> str | None:
    """`None` means retryable; any other value is the dead-letter reason."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in _RETRYABLE_STATUSES or status >= 500:
            return None
        # Design: "Terminal 4xx/422 (anything not 401/403/404/429) -> DEAD
        # immediately, no retry."
        return f"http_{status}"
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return None
    # An unrecognized exception type (a programming error, not a GitHub API
    # response) is never silently retried forever.
    return "unclassified_error"


def _delay_seconds(exc: Exception, attempt_count: int, rng: random.Random | None) -> float:
    """`Retry-After` (or, for a 429 lacking it, `X-RateLimit-Reset`) wins
    when present; otherwise full-jitter backoff whose window grows with
    `attempt_count` but stays bounded to `[MIN_DELAY_SECONDS,
    MAX_DELAY_SECONDS]` (design: "30s and 1h")."""
    if isinstance(exc, httpx.HTTPStatusError):
        header_delay = _header_delay_seconds(exc.response)
        if header_delay is not None:
            return min(MAX_DELAY_SECONDS, max(MIN_DELAY_SECONDS, header_delay))
    generator = rng if rng is not None else random.Random()
    upper_bound = min(MAX_DELAY_SECONDS, MIN_DELAY_SECONDS * (2.0 ** (attempt_count - 1)))
    return generator.uniform(MIN_DELAY_SECONDS, upper_bound)


def _header_delay_seconds(response: httpx.Response) -> float | None:
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return float(retry_after)
        except ValueError:
            return None
    reset = response.headers.get("X-RateLimit-Reset")
    if reset is not None:
        try:
            return float(reset) - time.time()
        except ValueError:
            return None
    return None
