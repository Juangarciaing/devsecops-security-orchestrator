"""Architecture guard: Prometheus remains outside domain and application layers."""

from __future__ import annotations

import ast
from pathlib import Path

_SOURCE_ROOT = Path(__file__).parents[2] / "src" / "orchestrator"
_PROTECTED_LAYERS = ("domain", "application")


def _prometheus_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(
                alias.name for alias in node.names if alias.name.startswith("prometheus")
            )
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("prometheus")
        ):
            imports.append(node.module)
    return imports


def test_domain_and_application_never_import_prometheus() -> None:
    forbidden = {
        str(path.relative_to(_SOURCE_ROOT)): _prometheus_imports(path)
        for layer in _PROTECTED_LAYERS
        for path in (_SOURCE_ROOT / layer).rglob("*.py")
        if _prometheus_imports(path)
    }

    assert forbidden == {}
