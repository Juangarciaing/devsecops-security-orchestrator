"""`FernetCredentialStore` — the `CredentialStorePort` adapter.

The **sole** module in this codebase permitted to import `cryptography`
(design D1/D2), mirroring `password_hasher.py` (argon2) / `api_key.py`
(hashlib) importing their respective crypto library only at the adapter
layer. `domain/` and `application/` MUST stay crypto-free — enforced by
`tests/unit/test_layering_boundaries.py`.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from orchestrator.domain.ports.credential_store_port import (
    CredentialSealError,
    CredentialStorePort,
    CredentialUnsealError,
    SealedCredential,
)
from orchestrator.domain.value_objects.enums import CredentialKind
from orchestrator.domain.value_objects.secret import Secret


class FernetCredentialStore(CredentialStorePort):
    """Envelope-encrypts a credential with Fernet (AES-128-CBC + HMAC-SHA256,
    versioned token, integrated authentication and timestamp).

    Fail-closed (design D2): constructed with `encryption_key=None` when
    `Settings.credential_encryption_key` is unset — a fully valid, bootable
    state for a public-repo-only deployment. `seal()`/`unseal()` only raise
    once a caller actually attempts to store or decrypt a credential.
    """

    def __init__(self, *, encryption_key: str | None) -> None:
        self._fernet = Fernet(encryption_key.encode("ascii")) if encryption_key else None

    def seal(self, plaintext: str, kind: CredentialKind) -> SealedCredential:
        if self._fernet is None:
            raise CredentialSealError(
                "credential storage is not configured on this deployment "
                "(credential_encryption_key is unset)"
            )
        ciphertext = self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")
        return SealedCredential(kind=kind, ciphertext=ciphertext)

    def unseal(self, sealed: SealedCredential) -> Secret:
        if self._fernet is None:
            raise CredentialUnsealError(
                "credential storage is not configured on this deployment "
                "(credential_encryption_key is unset)"
            )
        try:
            plaintext = self._fernet.decrypt(sealed.ciphertext.encode("ascii"))
        except InvalidToken as exc:
            raise CredentialUnsealError(
                "failed to decrypt the stored credential — the encryption "
                "key may have changed or the ciphertext is corrupted"
            ) from exc
        return Secret(plaintext.decode("utf-8"))
