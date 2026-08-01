"""`ScanStatusEvent` — the sole wire contract, identical on Redis and on the
SSE `data: ` line.

`json.dumps` escaping of control characters is what makes response-splitting
via a crafted payload structurally impossible (threat matrix): no field here
can ever contain a literal `\\n` in the serialized form.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from orchestrator.domain.value_objects.enums import ScanRunStatus


@dataclass(frozen=True, slots=True)
class ScanStatusEvent:
    """A single scan status transition, as published and streamed."""

    scan_run_id: uuid.UUID
    status: ScanRunStatus
    at: str

    def to_json(self) -> str:
        return json.dumps(
            {"scan_run_id": str(self.scan_run_id), "status": self.status.value, "at": self.at}
        )

    @classmethod
    def from_json(cls, raw: str) -> ScanStatusEvent:
        payload = json.loads(raw)
        return cls(
            scan_run_id=uuid.UUID(payload["scan_run_id"]),
            status=ScanRunStatus(payload["status"]),
            at=payload["at"],
        )
