"""`LoginRequest`/`TokenResponse` schemas — D5: JSON body, not OAuth2PasswordRequestForm."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestrator.application.dto.auth import LoginRequest, TokenResponse


def test_login_request_requires_email_and_password() -> None:
    payload = LoginRequest(email="user@example.com", password="s3cret-passw0rd")

    assert payload.email == "user@example.com"
    assert payload.password == "s3cret-passw0rd"


def test_login_request_rejects_missing_password() -> None:
    with pytest.raises(ValidationError):
        LoginRequest(email="user@example.com")  # type: ignore[call-arg]


def test_token_response_defaults_token_type_to_bearer() -> None:
    response = TokenResponse(access_token="a.b.c")

    assert response.token_type == "bearer"
    assert response.access_token == "a.b.c"
