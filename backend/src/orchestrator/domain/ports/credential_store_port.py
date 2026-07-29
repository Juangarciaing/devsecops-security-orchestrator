"""`CredentialStorePort` — contract for envelope-encrypting a repository
credential before persistence and decrypting it back at scan time.

Framework-free: this module MUST NOT import any encryption library — only
the concrete adapter (`infrastructure.security.credential_store`) does
that, mirroring `ContainerRunnerPort`'s "no `docker` SDK import" precedent
(design D1). Enforced by `tests/unit/test_layering_boundaries.py`.

Sync by design (mirrors `ContainerRunnerPort` D3): seal/unseal is
microseconds of CPU, not I/O — there is nothing to `await`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from orchestrator.domain.value_objects.enums import CredentialKind
from orchestrator.domain.value_objects.secret import Secret


@dataclass(frozen=True, slots=True)
class SealedCredential:
    """An encrypted credential ready to persist. `ciphertext` is opaque —
    its encoding is adapter-private; callers MUST NOT parse or inspect it."""

    kind: CredentialKind
    ciphertext: str


class CredentialSealError(Exception):
    """Raised when a plaintext credential cannot be sealed — e.g. no
    `credential_encryption_key` is configured on this deployment."""


class CredentialUnsealError(Exception):
    """Raised when a stored `SealedCredential` cannot be decrypted — e.g. the
    encryption key was rotated/removed, or the ciphertext is corrupted."""


class CredentialStorePort(ABC):
    """Contract for envelope-encrypting and decrypting one repository
    credential. Implementations MUST fail closed: `seal()` MUST raise
    `CredentialSealError` rather than persist plaintext when no key is
    configured; `unseal()` MUST raise `CredentialUnsealError` rather than
    return a wrong or partial value on decrypt failure.
    """

    @abstractmethod
    def seal(self, plaintext: str, kind: CredentialKind) -> SealedCredential:
        """Encrypt `plaintext` and tag it with `kind`.

        Raises `CredentialSealError` if no encryption key is configured on
        this deployment.
        """

    @abstractmethod
    def unseal(self, sealed: SealedCredential) -> Secret:
        """Decrypt `sealed` back into a redacting `Secret`.

        Raises `CredentialUnsealError` if the key is wrong/rotated/missing
        or the ciphertext is corrupted.
        """
