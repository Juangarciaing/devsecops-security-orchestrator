"""Module 12b PR1 task 2.8 — a pure, DB-independent proof that the three
`FindingDiffSets` classification predicates (ADDED/RESOLVED/CARRIED) are
pairwise disjoint on ANY set of findings satisfying the domain invariant
`first_seen_scan_run_id <= last_seen_scan_run_id` (upsert only ever advances
`last_seen` forward, Module 7 D4) — not just asserted in prose.

The live-Postgres partition itself (three indexed equality `SELECT`s) is
proven correct against a real seeded pair of adjacent runs in
`tests/integration/test_finding_repository.py::test_diff_between_runs_partitions_added_resolved_and_carried_exactly`.
This file instead proves the underlying set algebra holds in general, for
every fixture combination below, using the exact same predicates design D3
describes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

_NOW = datetime.now(UTC).replace(tzinfo=None)


@dataclass(frozen=True, slots=True)
class _FakeFindingRef:
    """A minimal stand-in for `Finding` — only the two fields the
    classification predicates read."""

    id: uuid.UUID
    first_seen_scan_run_id: uuid.UUID
    last_seen_scan_run_id: uuid.UUID


def _is_added(finding: _FakeFindingRef, latest_id: uuid.UUID) -> bool:
    return finding.first_seen_scan_run_id == latest_id


def _is_resolved(finding: _FakeFindingRef, baseline_id: uuid.UUID) -> bool:
    return finding.last_seen_scan_run_id == baseline_id


def _is_carried(finding: _FakeFindingRef, latest_id: uuid.UUID) -> bool:
    return (
        finding.last_seen_scan_run_id == latest_id and finding.first_seen_scan_run_id != latest_id
    )


def _build_fixture_findings(
    ancient_id: uuid.UUID, baseline_id: uuid.UUID, latest_id: uuid.UUID
) -> list[_FakeFindingRef]:
    """Every combination of `(first_seen, last_seen)` consistent with the
    invariant `first_seen <= last_seen` across 3 chronologically ordered
    runs (`ancient < baseline < latest`) — including the "resolved long
    before baseline" edge case that belongs to none of the three sets."""
    return [
        # ADDED: introduced exactly at latest.
        _FakeFindingRef(uuid.uuid4(), latest_id, latest_id),
        # RESOLVED: last seen at baseline, never re-observed at latest.
        _FakeFindingRef(uuid.uuid4(), ancient_id, baseline_id),
        _FakeFindingRef(uuid.uuid4(), baseline_id, baseline_id),
        # CARRIED: introduced before latest, still present at latest.
        _FakeFindingRef(uuid.uuid4(), ancient_id, latest_id),
        _FakeFindingRef(uuid.uuid4(), baseline_id, latest_id),
        # Excluded: already gone before the diff window even opened.
        _FakeFindingRef(uuid.uuid4(), ancient_id, ancient_id),
    ]


def test_added_resolved_and_carried_are_pairwise_disjoint_on_fixture_sets() -> None:
    ancient_id, baseline_id, latest_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    findings = _build_fixture_findings(ancient_id, baseline_id, latest_id)

    added_ids = {f.id for f in findings if _is_added(f, latest_id)}
    resolved_ids = {f.id for f in findings if _is_resolved(f, baseline_id)}
    carried_ids = {f.id for f in findings if _is_carried(f, latest_id)}

    assert added_ids & resolved_ids == set()
    assert added_ids & carried_ids == set()
    assert resolved_ids & carried_ids == set()

    # Sanity: the fixture actually exercises all three non-empty buckets,
    # plus at least one finding excluded from every bucket.
    assert len(added_ids) == 1
    assert len(resolved_ids) == 2
    assert len(carried_ids) == 2
    classified_ids = added_ids | resolved_ids | carried_ids
    assert len(classified_ids) < len(findings)


def test_disjointness_holds_for_every_first_seen_last_seen_pair_satisfying_the_invariant() -> None:
    """Exhaustive proof over every `(first_seen, last_seen)` pair drawn from
    3 candidate runs where `first_seen <= last_seen` (the only invariant the
    domain guarantees, Module 7 D4) — ADDED/RESOLVED/CARRIED never overlap,
    regardless of which specific pair a finding happens to have."""
    ancient_id, baseline_id, latest_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    ordered_runs = [ancient_id, baseline_id, latest_id]

    for first_index, first_seen in enumerate(ordered_runs):
        for last_seen in ordered_runs[first_index:]:  # enforce first_seen <= last_seen
            finding = _FakeFindingRef(uuid.uuid4(), first_seen, last_seen)

            is_added = _is_added(finding, latest_id)
            is_resolved = _is_resolved(finding, baseline_id)
            is_carried = _is_carried(finding, latest_id)

            memberships = [is_added, is_resolved, is_carried]
            assert sum(memberships) <= 1, (
                f"finding(first_seen={first_seen}, last_seen={last_seen}) matched "
                f"more than one of ADDED/RESOLVED/CARRIED: {memberships}"
            )
