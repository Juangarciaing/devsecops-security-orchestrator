"""Hexagonal-layering guard (Module 13a, tasks 5.1/5.2).

Adding tracing MUST NOT introduce any OpenTelemetry import/reference into
`domain/entities`, `domain/ports`, or `application/use_cases` — all
instrumentation (automatic and manual) belongs only in `infrastructure/`,
the API bootstrap layer, and `workers/` (spec: "Hexagonal Layering Stays
Intact"). This is an automated, standing guard so the invariant is enforced
going forward, not just checked once at implementation time.
"""

from __future__ import annotations

from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "orchestrator"
_GUARDED_DIRS = ("domain", "application")


def test_domain_and_application_have_zero_opentelemetry_references() -> None:
    offenders: list[str] = []
    for dirname in _GUARDED_DIRS:
        root = _SRC_ROOT / dirname
        assert root.is_dir(), f"expected {root} to exist"
        for path in sorted(root.rglob("*.py")):
            if "opentelemetry" in path.read_text(encoding="utf-8"):
                offenders.append(str(path.relative_to(_SRC_ROOT)))

    assert offenders == [], f"OpenTelemetry reference found in guarded layer(s): {offenders}"
