"""Structural placeholder proving pytest discovers the integration test tier.

Triangulation skipped: purely structural (proves test-tier discovery only),
no production behavior to exercise.
"""

from __future__ import annotations


def test_integration_tier_is_discoverable() -> None:
    assert "integration" == "integration"
