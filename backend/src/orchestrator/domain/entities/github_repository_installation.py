"""`GitHubRepositoryInstallation` entity — the GitHub App installation-to-
repository mapping (model landed in PR1; entity/port deferred to PR5, design:
"App credentials"/"Tokens"). No SQLAlchemy/Pydantic."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class GitHubRepositoryInstallation:
    """A repository's discovered GitHub App installation id. `checks_client`
    consults this via `GitHubRepositoryInstallationPort` before any network
    discovery round-trip, and refreshes it once on a `403`/`404`."""

    repository_id: uuid.UUID
    installation_id: int
