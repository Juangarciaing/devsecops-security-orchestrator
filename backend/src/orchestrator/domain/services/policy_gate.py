"""Pure repo-scoped quality-gate threshold — Module 12c.

Framework-free: this module MUST NOT import SQLAlchemy or Pydantic. The
blocking severity set is a named domain constant, not a per-repository
configurable setting (design D2) — no `CodeRepository` field, no migration,
no per-repo override. `evaluate_policy` is a pure function over the
already-shipped `FindingPort.open_counts_by_severity` (Module 12a) — no new
port method, no new query.
"""

from __future__ import annotations

from orchestrator.domain.value_objects.enums import FindingSeverity

#: Severities whose presence among currently-OPEN findings fails the policy
#: gate. `MEDIUM`/`LOW`/`INFO` never block — this is a FIXED global rule
#: (design D2), never a per-repository override.
POLICY_BLOCKING_SEVERITIES: frozenset[FindingSeverity] = frozenset(
    {FindingSeverity.CRITICAL, FindingSeverity.HIGH}
)


def evaluate_policy(open_counts: dict[FindingSeverity, int]) -> str:
    """Return `"fail"` if `open_counts` reports at least one open CRITICAL
    or HIGH finding, otherwise `"pass"`.

    `open_counts` is the SPARSE dict shape returned by
    `FindingPort.open_counts_by_severity` — only non-zero severities are
    present as keys. Reads via `.get(severity, 0)`, never direct indexing,
    so a repository whose open findings are entirely non-blocking (e.g. only
    MEDIUM) — where CRITICAL/HIGH keys are absent entirely, not
    present-with-zero — correctly evaluates to `"pass"`.
    """
    blocking_total = sum(open_counts.get(severity, 0) for severity in POLICY_BLOCKING_SEVERITIES)
    return "fail" if blocking_total > 0 else "pass"
