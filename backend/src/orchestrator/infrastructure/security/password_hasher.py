"""Argon2id password hashing (D1: `argon2-cffi`, not passlib/bcrypt).

Plaintext passwords MUST never be persisted or logged — `hash_password` is
the only path from plaintext to a storable value, and `verify_password` is
the only path back to a boolean, never to the plaintext itself.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    """Hash `plain` with argon2id. Returns a self-describing `$argon2id$...` string."""
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return `True` iff `plain` matches `hashed`. Never raises on mismatch."""
    try:
        return _hasher.verify(hashed, plain)
    except VerifyMismatchError:
        return False
