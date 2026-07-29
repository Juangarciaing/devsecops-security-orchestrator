"""`FernetCredentialStore` — the sole `cryptography` importer (design D1/D2).

Covers: round-trip seal/unseal correctness, decrypt failure on a wrong key
or corrupted ciphertext raising `CredentialUnsealError`, and fail-closed
`CredentialSealError` when no encryption key is configured.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from orchestrator.domain.ports.credential_store_port import (
    CredentialSealError,
    CredentialUnsealError,
    SealedCredential,
)
from orchestrator.domain.value_objects.enums import CredentialKind
from orchestrator.infrastructure.security.credential_store import FernetCredentialStore

_A_KEY = Fernet.generate_key().decode("ascii")
_A_DIFFERENT_KEY = Fernet.generate_key().decode("ascii")


def test_seal_then_unseal_round_trips_the_exact_plaintext() -> None:
    store = FernetCredentialStore(encryption_key=_A_KEY)

    sealed = store.seal("ghp_realtoken", CredentialKind.PERSONAL_ACCESS_TOKEN)
    secret = store.unseal(sealed)

    assert secret.reveal() == "ghp_realtoken"


def test_seal_produces_ciphertext_not_the_plaintext() -> None:
    store = FernetCredentialStore(encryption_key=_A_KEY)

    sealed = store.seal("ghp_realtoken", CredentialKind.PERSONAL_ACCESS_TOKEN)

    assert "ghp_realtoken" not in sealed.ciphertext
    assert sealed.kind is CredentialKind.PERSONAL_ACCESS_TOKEN


def test_seal_without_a_configured_key_raises_credential_seal_error() -> None:
    store = FernetCredentialStore(encryption_key=None)

    with pytest.raises(CredentialSealError):
        store.seal("ghp_realtoken", CredentialKind.PERSONAL_ACCESS_TOKEN)


def test_unseal_with_the_wrong_key_raises_credential_unseal_error() -> None:
    sealing_store = FernetCredentialStore(encryption_key=_A_KEY)
    sealed = sealing_store.seal("ghp_realtoken", CredentialKind.PERSONAL_ACCESS_TOKEN)

    wrong_key_store = FernetCredentialStore(encryption_key=_A_DIFFERENT_KEY)

    with pytest.raises(CredentialUnsealError):
        wrong_key_store.unseal(sealed)


def test_unseal_with_corrupted_ciphertext_raises_credential_unseal_error() -> None:
    store = FernetCredentialStore(encryption_key=_A_KEY)
    corrupted = SealedCredential(
        kind=CredentialKind.PERSONAL_ACCESS_TOKEN, ciphertext="not-a-real-fernet-token"
    )

    with pytest.raises(CredentialUnsealError):
        store.unseal(corrupted)


def test_unseal_without_a_configured_key_raises_credential_unseal_error() -> None:
    sealing_store = FernetCredentialStore(encryption_key=_A_KEY)
    sealed = sealing_store.seal("ghp_realtoken", CredentialKind.PERSONAL_ACCESS_TOKEN)

    unconfigured_store = FernetCredentialStore(encryption_key=None)

    with pytest.raises(CredentialUnsealError):
        unconfigured_store.unseal(sealed)
