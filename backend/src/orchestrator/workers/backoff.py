"""`backoff_jitter` — exponential backoff with a hard cap plus uniform jitter (D5).

Framework-free: this module MUST NOT import Celery or `Settings`. Celery's
module-level `@celery_app.task(...)` registration in `tasks/process_scan.py`
eagerly resolves `Settings()` at import time (the standard `-A module`
requirement, per `workers/celery_app.py`'s docstring) — keeping this pure
function import-independent from that lets unit tests import it directly
without needing valid `Settings` env vars just to collect the test module.
"""

from __future__ import annotations

import random

BACKOFF_BASE = 1.0
BACKOFF_CAP = 60.0
BACKOFF_JITTER = 1.0


def backoff_jitter(
    retries: int,
    *,
    base: float = BACKOFF_BASE,
    cap: float = BACKOFF_CAP,
    jitter: float = BACKOFF_JITTER,
    rng: random.Random | None = None,
) -> float:
    """`min(cap, base * 2**retries) + rng.uniform(0, jitter)`.

    Monotonically increasing in `retries` until the exponential term hits
    `cap`. `rng` defaults to a fresh `random.Random()`; tests inject a seeded
    instance for determinism.
    """
    generator = rng if rng is not None else random.Random()
    # `2.0**retries` (float base) rather than `2**retries`: `int ** int` is
    # typed `Any` in typeshed (the exponent could be negative, returning a
    # `float`), which would otherwise poison the whole expression to `Any`.
    return min(cap, base * (2.0**retries)) + generator.uniform(0, jitter)
