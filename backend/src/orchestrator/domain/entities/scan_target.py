"""ScanTarget domain entity.

Framework-free: this module MUST NOT import SQLAlchemy or Pydantic.

`ScanTarget` is a wholly independent aggregate (dast-scanner PR1, design D1 /
proposal D1-Option B) — NOT a `CodeRepository` variant. It has no git
identity (`provider`/`owner`/`name`/`clone_url`/`default_branch`) and no
credential fields, and no linkage to `CodeRepository` in this slice.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class ScanTarget:
    """A live, network-reachable URL registered for DAST scanning.

    `target_url` is this aggregate's natural dedup key (enforced at the DB
    layer by a UNIQUE constraint) — there is no compound identity tuple like
    `CodeRepository`'s `(provider, owner, name)`.
    """

    id: uuid.UUID
    name: str
    target_url: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
