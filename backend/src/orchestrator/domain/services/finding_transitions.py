"""Pure `Finding` suppression FSM — `open <-> suppressed` transitions.

Framework-free: this module MUST NOT import SQLAlchemy or Pydantic. No
pre-existing FSM lived on `Finding` before Module 8 (it is a bare
`@dataclass(slots=True)`) — this module IS that FSM, created fresh per the
Module 8 design decision "Suppression FSM location".

Deliberately stateless: these functions take the finding's CURRENT
`FindingStatus` and return the RESULTING `FindingStatus` (or raise). They
never touch a `Finding` instance or the persistence layer — the caller
(a Module 8 PR2 use case) is responsible for comparing the result against
the current status to decide whether a write (`FindingPort.update_status`)
is actually needed, and for persisting/redacting the outcome.
"""

from __future__ import annotations

from orchestrator.domain.value_objects.enums import FindingStatus

#: The only two statuses the suppress/unsuppress FSM manages. Any other
#: status (`RESOLVED`, `FALSE_POSITIVE`) is out of scope by design: those
#: transitions live outside this FSM's managed boundary and must never be
#: silently overwritten.
_MANAGED_STATUSES = frozenset({FindingStatus.OPEN, FindingStatus.SUPPRESSED})


class IllegalStatusTransitionError(Exception):
    """Raised when a suppress/unsuppress transition is attempted on a
    `Finding` whose current status is outside `{OPEN, SUPPRESSED}`.

    Maps to `409 Conflict` (RFC 7807 `problem+json`) at the router layer
    (Module 8 PR3). Carries `current_status` so callers can build a
    descriptive problem body without re-deriving it.
    """

    def __init__(self, current_status: FindingStatus, attempted: str) -> None:
        self.current_status = current_status
        self.attempted = attempted
        super().__init__(f"cannot {attempted} a finding with status {current_status.value!r}")


def suppress(current_status: FindingStatus) -> FindingStatus:
    """Return the resulting status for a suppress transition.

    - `OPEN` -> `SUPPRESSED`: the transition applies; the caller MUST persist it.
    - `SUPPRESSED` -> `SUPPRESSED`: idempotent no-op. Returning the SAME
      status the caller passed in is the "no write needed" signal.
    - Any other status -> raises `IllegalStatusTransitionError`.
    """
    if current_status not in _MANAGED_STATUSES:
        raise IllegalStatusTransitionError(current_status, "suppress")
    return FindingStatus.SUPPRESSED


def unsuppress(current_status: FindingStatus) -> FindingStatus:
    """Return the resulting status for an unsuppress transition.

    Mirrors `suppress`: `SUPPRESSED` -> `OPEN`, `OPEN` -> `OPEN` (idempotent
    no-op), any other status -> raises `IllegalStatusTransitionError`.
    """
    if current_status not in _MANAGED_STATUSES:
        raise IllegalStatusTransitionError(current_status, "unsuppress")
    return FindingStatus.OPEN
