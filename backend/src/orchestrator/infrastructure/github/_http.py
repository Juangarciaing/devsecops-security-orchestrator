"""Shared GitHub REST API request-header helper — `app_token_provider.py`
and `checks_client.py` both build the same `Authorization`+`Accept` header
shape (App JWT `Bearer` auth, installation-token `token` auth) and had each
grown their own copy before this extraction."""

from __future__ import annotations


def github_api_headers(authorization: str) -> dict[str, str]:
    return {"Authorization": authorization, "Accept": "application/vnd.github+json"}
