"""`Secret` — a redacting wrapper around a decrypted plaintext credential.

Framework-free: this module MUST NOT import SQLAlchemy, Pydantic, or any
encryption library — enforced by `tests/unit/test_layering_boundaries.py`.
Wrapping a decrypted credential in `Secret` (design D5) makes an accidental
leak into a log line, an f-string, an exception message, or a span
attribute non-leaking by construction — the plaintext is reachable only via
the explicit `.reveal()` escape hatch.
"""

from __future__ import annotations

from dataclasses import dataclass

_REDACTED = "Secret(***)"


@dataclass(frozen=True, slots=True)
class Secret:
    """A decrypted credential value that never renders as plaintext."""

    value: str

    def reveal(self) -> str:
        """Return the wrapped plaintext value. The only path back to it."""
        return self.value

    def __repr__(self) -> str:
        return _REDACTED

    def __str__(self) -> str:
        return _REDACTED
