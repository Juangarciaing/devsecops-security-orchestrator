"""Pydantic v2 I/O schemas for the login flow.

`LoginRequest` is a plain JSON body (D5), not `OAuth2PasswordRequestForm` —
keeps the request/response shape RFC-7807-consistent and avoids the
`python-multipart` dependency the form flow would require.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class LoginRequest(BaseModel):
    """Input schema for `POST /api/v1/auth/login`."""

    model_config = ConfigDict(extra="forbid")

    email: str
    password: str


class TokenResponse(BaseModel):
    """Output schema for a successful login."""

    model_config = ConfigDict(extra="forbid")

    access_token: str
    token_type: str = "bearer"
