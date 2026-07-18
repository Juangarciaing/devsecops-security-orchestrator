"""`backoff_jitter` (D5): exponential backoff, hard-capped, plus uniform jitter.

Pure function — no DB, no Celery machinery. Seedable via an injected
`random.Random` for deterministic assertions.
"""

from __future__ import annotations

import random

from orchestrator.workers.backoff import backoff_jitter


def test_backoff_jitter_grows_exponentially_before_cap() -> None:
    values = [backoff_jitter(r, cap=100.0, jitter=0.0, rng=random.Random(0)) for r in range(5)]
    assert values == sorted(values)
    assert values[0] < values[-1]


def test_backoff_jitter_caps_at_maximum() -> None:
    value = backoff_jitter(10, cap=5.0, jitter=0.0, rng=random.Random(0))
    assert value == 5.0


def test_backoff_jitter_adds_bounded_jitter() -> None:
    value = backoff_jitter(0, base=1.0, cap=100.0, jitter=2.0, rng=random.Random(7))
    assert 1.0 <= value < 3.0


def test_backoff_jitter_is_deterministic_with_seeded_rng() -> None:
    first = backoff_jitter(3, rng=random.Random(42))
    second = backoff_jitter(3, rng=random.Random(42))
    assert first == second


def test_backoff_jitter_defaults_use_module_constants() -> None:
    from orchestrator.workers.backoff import BACKOFF_CAP

    value = backoff_jitter(20, rng=random.Random(0))
    assert value <= BACKOFF_CAP + 1.0
