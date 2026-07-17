"""domain/ports/*.py MUST expose async-only, domain-entity-typed interfaces,
with zero SQLAlchemy import (same no-framework-imports style as
`test_no_framework_imports.py`, scoped to `domain/ports/`)."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from orchestrator.domain.ports.api_key_port import ApiKeyPort
from orchestrator.domain.ports.code_repository_port import CodeRepositoryPort
from orchestrator.domain.ports.finding_port import FindingPort
from orchestrator.domain.ports.scan_run_port import ScanRunPort
from orchestrator.domain.ports.scan_task_port import ScanTaskPort
from orchestrator.domain.ports.user_port import UserPort

PORTS_ROOT = Path(__file__).parents[3] / "src" / "orchestrator" / "domain" / "ports"

ALL_PORTS = (CodeRepositoryPort, ScanRunPort, ScanTaskPort, FindingPort, UserPort, ApiKeyPort)

FORBIDDEN_MODULE_PREFIXES = ("sqlalchemy",)


def _imported_module_names(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)

    return names


def _is_forbidden(name: str) -> bool:
    return any(
        name == prefix or name.startswith(f"{prefix}.") for prefix in FORBIDDEN_MODULE_PREFIXES
    )


def test_ports_package_has_no_sqlalchemy_imports() -> None:
    python_files = sorted(p for p in PORTS_ROOT.glob("*.py") if p.name != "__init__.py")
    assert python_files, "expected domain/ports/*.py files to exist"

    offenders: dict[str, set[str]] = {}
    for path in python_files:
        source = path.read_text(encoding="utf-8")
        forbidden = {name for name in _imported_module_names(source) if _is_forbidden(name)}
        if forbidden:
            offenders[str(path.relative_to(PORTS_ROOT))] = forbidden

    assert offenders == {}, f"sqlalchemy imports found in domain/ports/: {offenders}"


def test_every_port_declares_only_async_methods() -> None:
    for port_cls in ALL_PORTS:
        public_methods = [
            member
            for name, member in inspect.getmembers(port_cls, predicate=inspect.isfunction)
            if not name.startswith("_")
        ]
        assert public_methods, f"{port_cls.__name__} expected to declare abstract methods"

        for method in public_methods:
            assert inspect.iscoroutinefunction(method), (
                f"{port_cls.__name__}.{method.__name__} must be declared `async def`"
            )
