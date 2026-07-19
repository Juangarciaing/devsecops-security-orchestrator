"""`GitHubPushPayload` — minimal parse of a GitHub `push` webhook body.

Deliberately `extra="ignore"` (unlike this codebase's usual `extra="forbid"`
internal-API DTOs): a real GitHub push payload carries dozens of fields
(`pusher`, `commits`, `sender`, ...) this module never reads. Only
`repository.full_name` (split into owner/name), `ref`, and a resolved commit
sha are extracted.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _RepositoryPayload(BaseModel):
    """The subset of GitHub's nested `repository` object this module reads."""

    model_config = ConfigDict(extra="ignore")

    full_name: str


class _HeadCommitPayload(BaseModel):
    """The subset of GitHub's nested `head_commit` object this module reads."""

    model_config = ConfigDict(extra="ignore")

    id: str


class GitHubPushPayload(BaseModel):
    """Minimal shape of a GitHub `push` event webhook body."""

    model_config = ConfigDict(extra="ignore")

    ref: str
    repository: _RepositoryPayload
    after: str | None = None
    head_commit: _HeadCommitPayload | None = None

    @property
    def owner(self) -> str:
        """The `owner` half of `repository.full_name` (`owner/name`)."""
        owner, _, _ = self.repository.full_name.partition("/")
        return owner

    @property
    def name(self) -> str:
        """The `name` half of `repository.full_name` (`owner/name`)."""
        _, _, name = self.repository.full_name.partition("/")
        return name

    @property
    def commit_sha(self) -> str | None:
        """The pushed commit sha: `after` when present, else `head_commit.id`."""
        if self.after:
            return self.after
        if self.head_commit is not None:
            return self.head_commit.id
        return None
