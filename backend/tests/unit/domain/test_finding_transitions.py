"""`domain.services.finding_transitions` — pure suppress/unsuppress FSM.

Allowed edges are `OPEN <-> SUPPRESSED` only (spec: Requirement "Suppress
Finding" / "Unsuppress Finding"). Re-applying the same transition to a
finding already in the target state is an idempotent no-op, signalled by
returning the SAME status the caller passed in (so the caller can compare
`result == current_status` to know no write is needed). Any other current
status (`RESOLVED`, `FALSE_POSITIVE`) is out of scope and MUST raise
`IllegalStatusTransitionError` rather than silently overwrite triage state.
"""

from __future__ import annotations

import pytest

from orchestrator.domain.services.finding_transitions import (
    IllegalStatusTransitionError,
    suppress,
    unsuppress,
)
from orchestrator.domain.value_objects.enums import FindingStatus


def test_suppress_open_transitions_to_suppressed() -> None:
    assert suppress(FindingStatus.OPEN) == FindingStatus.SUPPRESSED


def test_suppress_already_suppressed_is_idempotent_no_op() -> None:
    result = suppress(FindingStatus.SUPPRESSED)

    assert result == FindingStatus.SUPPRESSED


def test_suppress_resolved_raises_illegal_status_transition_error() -> None:
    with pytest.raises(IllegalStatusTransitionError):
        suppress(FindingStatus.RESOLVED)


def test_suppress_false_positive_raises_illegal_status_transition_error() -> None:
    with pytest.raises(IllegalStatusTransitionError):
        suppress(FindingStatus.FALSE_POSITIVE)


def test_unsuppress_suppressed_transitions_to_open() -> None:
    assert unsuppress(FindingStatus.SUPPRESSED) == FindingStatus.OPEN


def test_unsuppress_already_open_is_idempotent_no_op() -> None:
    result = unsuppress(FindingStatus.OPEN)

    assert result == FindingStatus.OPEN


def test_unsuppress_resolved_raises_illegal_status_transition_error() -> None:
    with pytest.raises(IllegalStatusTransitionError):
        unsuppress(FindingStatus.RESOLVED)


def test_unsuppress_false_positive_raises_illegal_status_transition_error() -> None:
    with pytest.raises(IllegalStatusTransitionError):
        unsuppress(FindingStatus.FALSE_POSITIVE)


def test_illegal_status_transition_error_carries_current_status_for_409_mapping() -> None:
    try:
        suppress(FindingStatus.RESOLVED)
    except IllegalStatusTransitionError as exc:
        assert exc.current_status == FindingStatus.RESOLVED
    else:
        raise AssertionError("expected IllegalStatusTransitionError")
