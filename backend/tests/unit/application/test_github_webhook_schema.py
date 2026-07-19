"""`GitHubPushPayload` — minimal parse of a GitHub `push` webhook body (design).

Deliberately `extra="ignore"` (not this codebase's usual `extra="forbid"`):
a real GitHub push payload carries dozens of fields (`pusher`, `commits`,
`sender`, ...) we never read — this DTO only extracts `repository.full_name`
(owner/name split), `ref`, and a resolved commit sha (`after` if present,
else `head_commit.id`).

Flat file under `tests/unit/application/`, matching this codebase's
established DTO-test convention (`test_scan_trigger_schema.py`,
`test_code_repository_schema.py`) rather than a `dto/` subfolder — no
`tests/unit/application/dto/` directory exists anywhere else in this suite.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestrator.application.dto.github_webhook import GitHubPushPayload


def _payload(**overrides: object) -> dict[object, object]:
    defaults: dict[object, object] = {
        "ref": "refs/heads/main",
        "after": "deadbeef1234",
        "repository": {"full_name": "acme/widgets"},
        "head_commit": {"id": "headcommitsha"},
    }
    defaults.update(overrides)
    return defaults


def test_github_push_payload_splits_owner_and_name_from_full_name() -> None:
    payload = GitHubPushPayload.model_validate(_payload())

    assert payload.owner == "acme"
    assert payload.name == "widgets"


def test_github_push_payload_commit_sha_prefers_after() -> None:
    payload = GitHubPushPayload.model_validate(
        _payload(after="deadbeef1234", head_commit={"id": "differentsha"})
    )

    assert payload.commit_sha == "deadbeef1234"


def test_github_push_payload_commit_sha_falls_back_to_head_commit_id_when_after_absent() -> None:
    payload = GitHubPushPayload.model_validate(
        _payload(after=None, head_commit={"id": "headcommitsha"})
    )

    assert payload.commit_sha == "headcommitsha"


def test_github_push_payload_ref_is_read_verbatim() -> None:
    payload = GitHubPushPayload.model_validate(_payload(ref="refs/heads/develop"))

    assert payload.ref == "refs/heads/develop"


def test_github_push_payload_ignores_unknown_top_level_fields() -> None:
    payload = GitHubPushPayload.model_validate(
        _payload(pusher={"name": "octocat"}, sender={"login": "octocat"}, commits=[])
    )

    assert payload.owner == "acme"
    assert payload.name == "widgets"


def test_github_push_payload_raises_validation_error_when_repository_is_missing() -> None:
    payload = _payload()
    del payload["repository"]

    with pytest.raises(ValidationError):
        GitHubPushPayload.model_validate(payload)
