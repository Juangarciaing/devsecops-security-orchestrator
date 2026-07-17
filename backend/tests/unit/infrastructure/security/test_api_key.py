"""`generate_api_key`/`hash_api_key_secret` (task 3.4, design D2/data-model key format).

Key format: `dso_<prefix8>.<secret43>` — `key_prefix` is the non-secret unique
lookup id (`dso_<prefix8>`), `hashed_key` is SHA-256 of the secret half only.
The raw key is returned once; only `key_prefix`/`hashed_key` are ever stored.
"""

from __future__ import annotations

import hashlib

from orchestrator.infrastructure.security.api_key import generate_api_key, hash_api_key_secret


def test_generate_api_key_raw_key_matches_prefix_dot_secret_format() -> None:
    generated = generate_api_key()

    prefix, _, secret = generated.raw_key.partition(".")
    assert prefix == generated.key_prefix
    assert prefix.startswith("dso_")
    assert len(prefix) == len("dso_") + 8
    assert len(secret) == 43


def test_generate_api_key_hashed_key_is_sha256_of_the_secret_half() -> None:
    generated = generate_api_key()
    _, _, secret = generated.raw_key.partition(".")

    assert generated.hashed_key == hashlib.sha256(secret.encode("utf-8")).hexdigest()
    assert generated.hashed_key == hash_api_key_secret(secret)


def test_generate_api_key_produces_unique_values_across_calls() -> None:
    first = generate_api_key()
    second = generate_api_key()

    assert first.raw_key != second.raw_key
    assert first.key_prefix != second.key_prefix
    assert first.hashed_key != second.hashed_key


def test_hash_api_key_secret_never_leaks_the_plaintext_secret() -> None:
    hashed = hash_api_key_secret("super-secret-value")

    assert "super-secret-value" not in hashed
