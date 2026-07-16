"""Framework-free domain entities."""

from __future__ import annotations

from orchestrator.domain.entities.code_repository import CodeRepository
from orchestrator.domain.entities.finding import Finding
from orchestrator.domain.entities.scan_run import ScanRun
from orchestrator.domain.entities.scan_task import ScanTask

__all__ = ["CodeRepository", "Finding", "ScanRun", "ScanTask"]
