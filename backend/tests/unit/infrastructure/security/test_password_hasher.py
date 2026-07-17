"""`hash_password`/`verify_password` — argon2id hashing, no plaintext leakage."""

from __future__ import annotations

from orchestrator.infrastructure.security.password_hasher import hash_password, verify_password


def test_hash_password_does_not_return_plaintext() -> None:
    hashed = hash_password("correct horse battery staple")

    assert hashed != "correct horse battery staple"
    assert hashed.startswith("$argon2id$")


def test_verify_password_succeeds_for_correct_password() -> None:
    hashed = hash_password("correct horse battery staple")

    assert verify_password("correct horse battery staple", hashed) is True


def test_verify_password_fails_for_wrong_password() -> None:
    hashed = hash_password("correct horse battery staple")

    assert verify_password("wrong password", hashed) is False


def test_hash_password_is_salted_and_produces_different_hashes() -> None:
    first = hash_password("same-password")
    second = hash_password("same-password")

    assert first != second
    assert verify_password("same-password", first) is True
    assert verify_password("same-password", second) is True
