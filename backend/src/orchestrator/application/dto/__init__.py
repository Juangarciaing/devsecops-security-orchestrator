"""Pydantic v2 I/O schemas (DTOs) for the application boundary.

These mirror the domain entities' fields for I/O only. They are a DISTINCT
layer from both the domain entities and the SQLAlchemy ORM models — never the
same class (decision D3).
"""

from __future__ import annotations

from orchestrator.application.dto.code_repository import (
    CodeRepositoryCreate,
    CodeRepositoryRead,
)
from orchestrator.application.dto.finding import FindingCreate, FindingRead
from orchestrator.application.dto.scan_run import ScanRunCreate, ScanRunRead
from orchestrator.application.dto.scan_task import ScanTaskCreate, ScanTaskRead

__all__ = [
    "CodeRepositoryCreate",
    "CodeRepositoryRead",
    "FindingCreate",
    "FindingRead",
    "ScanRunCreate",
    "ScanRunRead",
    "ScanTaskCreate",
    "ScanTaskRead",
]
