"""Architecture guard (Module 13c PR8, spec's "no mid-scan Docker fallback"
invariant): `process_scan_task`'s real flow MUST NOT import anything from
the Kubernetes execution package. There is structurally no code path inside
the active task body that could pivot from Docker to Kubernetes — or back —
once a scan has started; Celery alone is ever the retry authority. Mirrors
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


def test_process_scan_task_never_imports_kubernetes_execution() -> None:
    forbidden = [
        module
        for module in _module_imports(_PROCESS_SCAN_MODULE)
        if "kubernetes" in module
    ]

    assert forbidden == []


def test_process_scan_task_selects_exactly_one_docker_factory_call() -> None:
    """`_checkout_and_scan` MUST call `create_scan_execution` (the Docker
    descriptor factory) exactly once — no conditional branch that could try
    a second, different backend after the first attempt started."""
    tree = ast.parse(_PROCESS_SCAN_MODULE.read_text(encoding="utf-8"))
    calls = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "create_scan_execution"
    ]

    assert len(calls) == 1
