"""`domain.services.policy_gate` — pure repo-scoped quality-gate threshold.

Verdict is a pure function over the SPARSE `open_counts_by_severity` dict
(Module 12a): `"fail"` iff the sum of open CRITICAL + HIGH is greater than
zero, otherwise `"pass"`. `MEDIUM`/`LOW`/`INFO` never affect the verdict —
this is a fixed global rule (design D2), not a per-repository override.
"""

from __future__ import annotations

import pytest

from orchestrator.domain.services.policy_gate import (
    POLICY_BLOCKING_SEVERITIES,
    evaluate_policy,
)
from orchestrator.domain.value_objects.enums import FindingSeverity


def test_blocking_severities_are_exactly_critical_and_high() -> None:
    assert POLICY_BLOCKING_SEVERITIES == frozenset({FindingSeverity.CRITICAL, FindingSeverity.HIGH})


@pytest.mark.parametrize(
    ("open_counts", "expected_verdict"),
    [
        ({}, "pass"),
        ({FindingSeverity.HIGH: 1}, "fail"),
        ({FindingSeverity.CRITICAL: 2}, "fail"),
        (
            {FindingSeverity.MEDIUM: 9, FindingSeverity.LOW: 9, FindingSeverity.INFO: 9},
            "pass",
        ),
        (
            {FindingSeverity.CRITICAL: 1, FindingSeverity.HIGH: 3, FindingSeverity.LOW: 5},
            "fail",
        ),
    ],
)
def test_evaluate_policy_threshold_table(
    open_counts: dict[FindingSeverity, int], expected_verdict: str
) -> None:
    assert evaluate_policy(open_counts) == expected_verdict


def test_evaluate_policy_sparse_dict_absent_blocking_key_is_treated_as_zero() -> None:
    """The repository has ONLY open MEDIUM findings — CRITICAL/HIGH keys are
    entirely ABSENT from the dict (not present-with-zero). Naive direct
    indexing (`open_counts[FindingSeverity.CRITICAL]`) would raise `KeyError`
    here; `evaluate_policy` MUST use `.get(severity, 0)` instead."""
    open_counts = {FindingSeverity.MEDIUM: 4}

    assert evaluate_policy(open_counts) == "pass"
