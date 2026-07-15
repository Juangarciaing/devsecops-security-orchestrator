"""Structural placeholder proving pytest discovers the unit test tier.

Triangulation skipped: purely structural (proves test-tier discovery only),
no production behavior to exercise — matches the strict-tdd skip condition for
config/constant/structural tasks.
"""

from __future__ import annotations


def test_unit_tier_is_discoverable() -> None:
    assert "unit" == "unit"
