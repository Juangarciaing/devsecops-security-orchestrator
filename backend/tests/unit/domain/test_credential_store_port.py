"""`CredentialStorePort` — framework-free contract: `seal`/`unseal` over an
opaque `SealedCredential` (design D1). This module MUST NOT import
`cryptography` — only the concrete `FernetCredentialStore` adapter does."""

from __future__ import annotations

import ast
import inspect
from abc import ABC
from pathlib import Path

from orchestrator.domain.ports.credential_store_port import (
    CredentialSealError,
    CredentialStorePort,
    CredentialUnsealError,
    SealedCredential,
)
from orchestrator.domain.value_objects.enums import CredentialKind
from orchestrator.domain.value_objects.secret import Secret

PORT_MODULE_PATH = (
    Path(__file__).parents[3]
    / "src"
    / "orchestrator"
    / "domain"
    / "ports"
    / "credential_store_port.py"
)


def _imported_module_names(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names


def test_credential_store_port_module_never_imports_cryptography() -> None:
    source = PORT_MODULE_PATH.read_text(encoding="utf-8")
    imported = _imported_module_names(source)
    forbidden = {name for name in imported if name == "cryptography" or name.startswith(
        "cryptography."
    )}
    assert forbidden == set(), f"domain port must not import cryptography, found: {forbidden}"


def test_credential_store_port_is_an_abc() -> None:
    assert issubclass(CredentialStorePort, ABC)


def test_credential_store_port_declares_seal_and_unseal() -> None:
    assert "seal" in CredentialStorePort.__abstractmethods__
    assert "unseal" in CredentialStorePort.__abstractmethods__
    assert not inspect.iscoroutinefunction(CredentialStorePort.seal)
    assert not inspect.iscoroutinefunction(CredentialStorePort.unseal)


def test_sealed_credential_is_frozen_and_slotted() -> None:
    sealed = SealedCredential(kind=CredentialKind.PERSONAL_ACCESS_TOKEN, ciphertext="opaque")

    assert sealed.kind is CredentialKind.PERSONAL_ACCESS_TOKEN
    assert sealed.ciphertext == "opaque"
    assert not hasattr(sealed, "__dict__")  # slots=True


def test_credential_seal_error_is_an_exception() -> None:
    assert issubclass(CredentialSealError, Exception)


def test_credential_unseal_error_is_an_exception() -> None:
    assert issubclass(CredentialUnsealError, Exception)


class _FakeCredentialStore(CredentialStorePort):
    """Minimal concrete implementation proving the ABC contract is usable."""

    def seal(self, plaintext: str, kind: CredentialKind) -> SealedCredential:
        return SealedCredential(kind=kind, ciphertext=f"sealed:{plaintext}")

    def unseal(self, sealed: SealedCredential) -> Secret:
        return Secret(sealed.ciphertext.removeprefix("sealed:"))


def test_fake_implementation_satisfies_the_contract() -> None:
    store: CredentialStorePort = _FakeCredentialStore()
    sealed = store.seal("ghp_token", CredentialKind.PERSONAL_ACCESS_TOKEN)

    secret = store.unseal(sealed)

    assert secret.reveal() == "ghp_token"
