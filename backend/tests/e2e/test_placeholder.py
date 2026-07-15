"""Structural placeholder proving pytest discovers the e2e test tier.

Triangulation skipped: purely structural (proves test-tier discovery only),
no production behavior to exercise. Real end-to-end journeys land as later
modules ship real API/worker flows.
"""

from __future__ import annotations


def test_e2e_tier_is_discoverable() -> None:
    assert "e2e" == "e2e"
