"""The domain layer MUST stay framework-free: no SQLAlchemy, Pydantic, or
`docker` SDK imports (Module 6: `ContainerRunnerPort` is framework-free —
only `infrastructure.container.docker_container_runner` imports `docker`)."""

from __future__ import annotations

import ast
from pathlib import Path

DOMAIN_ROOT = Path(__file__).parents[3] / "src" / "orchestrator" / "domain"

FORBIDDEN_MODULE_PREFIXES = ("sqlalchemy", "pydantic", "docker")


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


def _forbidden_imports(module_names: set[str]) -> set[str]:
    return {name for name in module_names if _is_forbidden(name)}


def test_domain_package_has_no_framework_imports() -> None:
    python_files = sorted(DOMAIN_ROOT.rglob("*.py"))
    assert python_files, "expected domain/*.py files to exist"

    offenders: dict[str, set[str]] = {}
    for path in python_files:
        source = path.read_text(encoding="utf-8")
        forbidden = _forbidden_imports(_imported_module_names(source))
        if forbidden:
            offenders[str(path.relative_to(DOMAIN_ROOT))] = forbidden

    assert offenders == {}, f"framework imports found in domain/: {offenders}"
