"""`Secret` — a redacting wrapper so a decrypted credential can never leak via
`repr()`/`str()`/an f-string/an exception message by construction (design D5).
"""

from __future__ import annotations

import pytest

from orchestrator.domain.value_objects.secret import Secret


def test_secret_repr_never_reveals_the_wrapped_value() -> None:
    secret = Secret("ghp_supersensitivetoken")

    assert repr(secret) == "Secret(***)"
    assert "ghp_supersensitivetoken" not in repr(secret)


def test_secret_str_never_reveals_the_wrapped_value() -> None:
    secret = Secret("ghp_supersensitivetoken")

    assert str(secret) == "Secret(***)"
    assert "ghp_supersensitivetoken" not in str(secret)


def test_secret_in_fstring_never_reveals_the_wrapped_value() -> None:
    secret = Secret("ghp_supersensitivetoken")

    rendered = f"token={secret}"

    assert rendered == "token=Secret(***)"
    assert "ghp_supersensitivetoken" not in rendered


def test_secret_reveal_returns_the_exact_wrapped_value() -> None:
    secret = Secret("ghp_supersensitivetoken")

    assert secret.reveal() == "ghp_supersensitivetoken"


def test_secret_is_frozen_and_slotted() -> None:
    secret = Secret("ghp_supersensitivetoken")

    with pytest.raises((AttributeError, TypeError)):
        secret.value = "changed"  # type: ignore[misc]

    assert not hasattr(secret, "__dict__")  # slots=True
