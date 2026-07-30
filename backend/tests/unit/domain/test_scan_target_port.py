"""`ScanTargetPort` — persistence contract shape, mirroring
`CodeRepositoryPort`'s conventions minus git-identity lookups.

`get_by_url` replaces `CodeRepositoryPort.get_by_identity` — a `ScanTarget`'s
only natural lookup key besides `id` is `target_url` (design D-file-changes:
"CodeRepositoryPort shape, get_by_identity→get_by_url").
"""

from __future__ import annotations

import inspect

from orchestrator.domain.ports.scan_target_port import ScanTargetPort

_EXPECTED_ABSTRACT_METHODS = {
    "get_by_id",
    "get_by_url",
    "list_all",
    "list_active",
    "create",
    "update",
    "soft_delete",
}


def test_port_declares_expected_abstract_methods() -> None:
    assert _EXPECTED_ABSTRACT_METHODS <= ScanTargetPort.__abstractmethods__


def test_all_methods_are_coroutine_functions() -> None:
    for name in _EXPECTED_ABSTRACT_METHODS:
        method = getattr(ScanTargetPort, name)
        assert inspect.iscoroutinefunction(method), f"{name} must be declared `async def`"


def test_port_has_no_git_identity_lookup() -> None:
    """No `get_by_identity` — `ScanTarget` has no `(provider, owner, name)`
    concept (confirmed user decision: independent entity, no git identity)."""
    assert not hasattr(ScanTargetPort, "get_by_identity")
