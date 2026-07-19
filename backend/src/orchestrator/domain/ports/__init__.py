"""Framework-free port interfaces: async repository ports plus the sync
`ContainerRunnerPort` (container orchestration is blocking I/O — see its
module docstring for why it is not async like the others).
"""

from __future__ import annotations

from orchestrator.domain.ports.api_key_port import ApiKeyPort
from orchestrator.domain.ports.code_repository_port import CodeRepositoryPort
from orchestrator.domain.ports.container_runner_port import (
    ContainerRunnerPort,
    ResourceLimits,
    RunResult,
)
from orchestrator.domain.ports.finding_port import FindingPort
from orchestrator.domain.ports.scan_run_port import ScanRunPort
from orchestrator.domain.ports.scan_task_port import ScanTaskPort
from orchestrator.domain.ports.user_port import UserPort
from orchestrator.domain.ports.webhook_delivery_port import WebhookDeliveryPort

__all__ = [
    "ApiKeyPort",
    "CodeRepositoryPort",
    "ContainerRunnerPort",
    "FindingPort",
    "ResourceLimits",
    "RunResult",
    "ScanRunPort",
    "ScanTaskPort",
    "UserPort",
    "WebhookDeliveryPort",
]
