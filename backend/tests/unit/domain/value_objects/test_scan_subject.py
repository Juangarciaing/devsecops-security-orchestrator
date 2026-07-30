"""`ScanSubject` exactly-one subject invariant."""

from __future__ import annotations

import uuid

import pytest

from orchestrator.domain.value_objects.scan_subject import (
    InvalidScanSubjectError,
    ScanSubject,
    ScanSubjectKind,
)


@pytest.mark.parametrize(
    ("repository_id", "scan_target_id"),
    [(uuid.uuid4(), uuid.uuid4()), (None, None)],
)
def test_from_columns_rejects_both_or_neither_subject(
    repository_id: uuid.UUID | None, scan_target_id: uuid.UUID | None
) -> None:
    with pytest.raises(InvalidScanSubjectError):
        ScanSubject.from_columns(repository_id, scan_target_id)


def test_repository_subject_exposes_only_repository_id() -> None:
    repository_id = uuid.uuid4()

    subject = ScanSubject.from_columns(repository_id, None)

    assert subject.kind is ScanSubjectKind.REPOSITORY
    assert subject.repository_id == repository_id
    assert subject.scan_target_id is None


def test_target_subject_exposes_only_scan_target_id() -> None:
    target_id = uuid.uuid4()

    subject = ScanSubject.from_columns(None, target_id)

    assert subject.kind is ScanSubjectKind.SCAN_TARGET
    assert subject.repository_id is None
    assert subject.scan_target_id == target_id
