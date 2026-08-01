"""Architecture guard (Module 13c PR8, spec's "no mid-scan Docker fallback"
invariant, updated by k8s-backend-enable PR6/design D-Routing): once a scan
attempt starts, `process_scan_task` MUST NOT be able to pivot from Docker to
Kubernetes — or back — mid-flight; Celery alone is ever the retry authority.

Before k8s-backend-enable, Kubernetes was structurally unreachable from this
module at all, so "never imports anything Kubernetes" was a valid (if
stricter-than-necessary) proxy for that invariant. D-Routing now requires
`process_scan.py` to route to a real Kubernetes executor via the ONE
sanctioned entry point (`backend_selection.create_kubernetes_scan_execution`)
plus the two documented, deterministic exception types
(`kubernetes_scan_execution.KubernetesWorkloadFailedError`/
`KubernetesPrivateRepositoryError`) — so the import itself is no longer
forbidden. What must still hold, and what these tests check instead: this
module never reaches PAST that sanctioned surface into any other Kubernetes
submodule (the job runner, the cluster capability adapter, the preflight
module, etc.), and the actual per-call routing/execution shape (exactly one
factory call site per backend, exactly one `execute()` call) never allows a
same-task pivot between backends. Mirrors
`test_prometheus_import_boundary.py`'s AST-based import-boundary pattern.
"""

from __future__ import annotations

import ast
from pathlib import Path

_PROCESS_SCAN_MODULE = (
    Path(__file__).parents[2]
    / "src"
    / "orchestrator"
    / "workers"
    / "tasks"
    / "process_scan.py"
)


def _module_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports


#: The ONLY Kubernetes submodules `process_scan.py` may import from
#: (k8s-backend-enable PR6, design D-Routing): the sanctioned factory
#: (`backend_selection.create_kubernetes_scan_execution`) and the two
#: deterministic exception types it/the bridge raise. Anything else — the
#: job runner, cluster capability adapter, preflight module, mapping module,
#: etc. — reaching directly into `process_scan.py` would mean this task is
#: bypassing the sanctioned entry point, exactly the kind of structural drift
#: this guard exists to catch.
_SANCTIONED_KUBERNETES_MODULES = frozenset(
    {
        "orchestrator.infrastructure.kubernetes.backend_selection",
        "orchestrator.infrastructure.kubernetes.kubernetes_scan_execution",
    }
)


def test_process_scan_task_only_imports_kubernetes_through_the_sanctioned_factory() -> None:
    kubernetes_imports = {
        module
        for module in _module_imports(_PROCESS_SCAN_MODULE)
        if "kubernetes" in module
    }

    assert kubernetes_imports == _SANCTIONED_KUBERNETES_MODULES


def _function_body(name: str) -> ast.FunctionDef:
    tree = ast.parse(_PROCESS_SCAN_MODULE.read_text(encoding="utf-8"))
    (function,) = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    return function


def test_checkout_and_scan_selects_exactly_one_factory_call_per_backend() -> None:
    """`_checkout_and_scan` MUST call each backend's factory
    (`create_scan_execution`/`create_kubernetes_scan_execution`) from exactly
    one call site, and the resolved executor's `.execute()` from exactly one
    call site WITHIN THIS FUNCTION — no conditional branch that could try a
    second, different backend, or execute twice, after the first attempt
    started. Scoped to `_checkout_and_scan` itself (not the whole module) —
    `_execute_target_scan` (the DAST-only, checkout-free sibling) has its own,
    unrelated single `execute()` call site."""
    function = _function_body("_checkout_and_scan")
    call_names = [
        node.func.id
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    execute_calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute"
    ]

    assert call_names.count("create_scan_execution") == 1
    assert call_names.count("create_kubernetes_scan_execution") == 1
    assert len(execute_calls) == 1
