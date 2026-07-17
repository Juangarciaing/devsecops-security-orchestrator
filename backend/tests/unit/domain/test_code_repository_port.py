"""`CodeRepositoryPort` extension — `list_active`, `update`, `soft_delete`.

The existing `delete` method (cascade-delete semantics) MUST stay defined and
untouched; soft-delete is a distinct abstract method (design decision:
soft-delete surface).
"""

from __future__ import annotations

import inspect

from orchestrator.domain.ports.code_repository_port import CodeRepositoryPort

_NEW_ABSTRACT_METHODS = {"list_active", "update", "soft_delete"}


def test_port_declares_new_abstract_methods() -> None:
    assert _NEW_ABSTRACT_METHODS <= CodeRepositoryPort.__abstractmethods__


def test_new_methods_are_coroutine_functions() -> None:
    for name in _NEW_ABSTRACT_METHODS:
        method = getattr(CodeRepositoryPort, name)
        assert inspect.iscoroutinefunction(method), f"{name} must be declared `async def`"


def test_delete_method_still_defined_and_unchanged() -> None:
    assert "delete" in CodeRepositoryPort.__abstractmethods__
    assert "cascades to dependents" in (CodeRepositoryPort.delete.__doc__ or "")
