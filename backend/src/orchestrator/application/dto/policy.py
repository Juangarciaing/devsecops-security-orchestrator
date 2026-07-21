"""Pydantic v2 I/O schema for the repo-scoped quality-gate check
(Module 12c). Powers `GET /repositories/{id}/policy-check`.

Role-agnostic (design D3): the body carries only `verdict`,
`blocking_severities`, and per-severity `violating_counts` — never
finding-level bodies (`raw_evidence`/`snippet`/`file_path`/`line_number`), so
member and admin callers receive byte-identical responses. No
`redact_finding_for_role` call is needed or correct here (contrast
`get_repository_diff`, which returns finding bodies and MUST redact).
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict

from orchestrator.domain.value_objects.enums import FindingSeverity


class RepositoryPolicyRead(BaseModel):
    """Response body for `GET /repositories/{id}/policy-check`.

    `violating_counts` is SPARSE and scoped to
    `POLICY_BLOCKING_SEVERITIES` only — a severity absent from the dict
    means zero open findings of that severity (mirrors `current_open`'s
    sparse-dict convention from `RepositoryTrendsRead`). `MEDIUM`/`LOW`/
    `INFO` open counts are intentionally never surfaced here since they
    never affect `verdict`.
    """

    model_config = ConfigDict(extra="forbid")

    repository_id: uuid.UUID
    verdict: str
    blocking_severities: list[FindingSeverity]
    violating_counts: dict[FindingSeverity, int]
