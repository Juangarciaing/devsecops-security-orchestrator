"""Contract test (design Testing Strategy): downstream routers import
`get_current_user`/`require_role` from `dependencies.auth` UNCHANGED — they
must not redefine, wrap, or shadow the canonical DI guard surface (task 4.8).
"""

from __future__ import annotations

import inspect

from orchestrator.api.v1.dependencies import auth as auth_dependencies
from orchestrator.api.v1.routers import auth as auth_router_module
from orchestrator.api.v1.routers import users as users_router_module


def test_auth_router_imports_the_canonical_get_current_user_unmodified() -> None:
    assert auth_router_module.get_current_user is auth_dependencies.get_current_user


def test_users_router_imports_the_canonical_require_role_factory_unmodified() -> None:
    assert users_router_module.require_role is auth_dependencies.require_role


def test_require_role_factory_signature_is_unchanged() -> None:
    signature = inspect.signature(auth_dependencies.require_role)
    assert list(signature.parameters) == ["required"]
