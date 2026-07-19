"""domain/ports/*.py MUST expose async-only, domain-entity-typed interfaces,
with zero SQLAlchemy import (same no-framework-imports style as
`test_no_framework_imports.py`, scoped to `domain/ports/`)."""

from __future__ import annotations

import ast
import asyncio
import inspect
import uuid
from datetime import UTC, datetime
from pathlib import Path

from orchestrator.domain.ports.api_key_port import ApiKeyPort
from orchestrator.domain.ports.code_repository_port import CodeRepositoryPort
from orchestrator.domain.ports.finding_port import FindingPort
from orchestrator.domain.ports.scan_run_port import ScanRunPort
from orchestrator.domain.ports.scan_task_port import ScanTaskPort
from orchestrator.domain.ports.user_port import UserPort
from orchestrator.domain.value_objects.enums import ScannerType

PORTS_ROOT = Path(__file__).parents[3] / "src" / "orchestrator" / "domain" / "ports"
_NOW = datetime.now(UTC).replace(tzinfo=None)

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


def test_scan_task_port_declares_find_active_task() -> None:
    """`ScanTaskPort` gains `find_active_task` (D3) — used by `trigger_scan` for idempotency."""
    assert "find_active_task" in ScanTaskPort.__abstractmethods__
    assert inspect.iscoroutinefunction(ScanTaskPort.find_active_task)


def test_scan_run_port_declares_list_paginated() -> None:
    """`ScanRunPort` gains `list_paginated` — powers `GET /scans` (design deviation #7:
    the list endpoint was never paginated before this module)."""
    assert "list_paginated" in ScanRunPort.__abstractmethods__
    assert inspect.iscoroutinefunction(ScanRunPort.list_paginated)


def test_scanner_adapter_port_is_a_framework_free_abc_with_scan_parse_supports() -> None:
    """Module 7 D1: `ScannerAdapterPort` is a sync (not async — matches
    `ContainerRunnerPort`, Module 6 D3) ABC with `scan`/`parse`/`supports`."""
    from orchestrator.domain.ports.scanner_adapter_port import ScannerAdapterPort

    assert inspect.isabstract(ScannerAdapterPort)
    assert ScannerAdapterPort.__abstractmethods__ == frozenset({"scan", "parse", "supports"})
    for method_name in ("scan", "parse", "supports"):
        method = getattr(ScannerAdapterPort, method_name)
        assert not inspect.iscoroutinefunction(method), (
            f"ScannerAdapterPort.{method_name} must be sync (Module 6 D3 precedent)"
        )

    module_path = PORTS_ROOT / "scanner_adapter_port.py"
    source = module_path.read_text(encoding="utf-8")
    forbidden = _imported_module_names(source) & {"sqlalchemy", "pydantic", "docker"}
    assert forbidden == set(), f"framework imports found in scanner_adapter_port.py: {forbidden}"


def test_scanner_adapter_port_cannot_be_instantiated_without_implementing_all_methods() -> None:
    from orchestrator.domain.ports.scanner_adapter_port import ScannerAdapterPort

    class _IncompleteAdapter(ScannerAdapterPort):
        def scan(self, volume_name: str) -> object:
            raise NotImplementedError

    try:
        _IncompleteAdapter()  # type: ignore[abstract]
    except TypeError as exc:
        assert "parse" in str(exc) or "supports" in str(exc)
    else:
        raise AssertionError("expected TypeError: abstract methods not implemented")


def test_scanner_adapter_port_full_implementation_can_be_instantiated_and_used() -> None:
    from orchestrator.domain.ports.scanner_adapter_port import ScannerAdapterPort

    class _FakeAdapter(ScannerAdapterPort):
        def scan(self, volume_name: str) -> str:
            return f"ran:{volume_name}"

        def parse(self, result: object, scan_task_id: uuid.UUID) -> list[object]:
            return [result]

        def supports(self, scanner_type: ScannerType) -> bool:
            return scanner_type == ScannerType.SECRETS

    adapter = _FakeAdapter()
    assert adapter.scan("vol-1") == "ran:vol-1"
    task_id = uuid.uuid4()
    assert adapter.parse("raw-result", task_id) == ["raw-result"]
    assert adapter.supports(ScannerType.SECRETS) is True
    assert adapter.supports(ScannerType.SAST) is False


def test_finding_port_declares_bulk_upsert_and_count_by_last_seen_scan_run() -> None:
    """Module 7 D4/D5: cross-run dedup promotes `bulk_upsert_findings`/
    `count_by_last_seen_scan_run` onto `FindingPort` itself — unlike PR1's
    `count_by_scan_task` precedent (an adapter-only helper), dedup counting is
    now a core `FindingPort` concern, not a single call-site helper."""
    assert "bulk_upsert_findings" in FindingPort.__abstractmethods__
    assert "count_by_last_seen_scan_run" in FindingPort.__abstractmethods__
    assert inspect.iscoroutinefunction(FindingPort.bulk_upsert_findings)
    assert inspect.iscoroutinefunction(FindingPort.count_by_last_seen_scan_run)


def test_finding_port_full_implementation_can_be_instantiated_and_used() -> None:
    """Unit-level calling-contract coverage for `bulk_upsert_findings`/
    `count_by_last_seen_scan_run` via a fake `FindingPort` — no SQLite
    `ON CONFLICT` variant here; the real Postgres upsert/race semantics are
    integration-only coverage (`tests/integration/test_finding_repository.py`)."""
    from orchestrator.domain.entities.finding import Finding
    from orchestrator.domain.value_objects.enums import FindingSeverity, FindingStatus

    class _FakeFindingRepository(FindingPort):
        def __init__(self) -> None:
            self.upserted: list[tuple[uuid.UUID, uuid.UUID, list[Finding]]] = []
            self.counted: list[uuid.UUID] = []

        async def get_by_id(self, finding_id: uuid.UUID) -> Finding | None:
            return None

        async def list_by_scan_task(self, scan_task_id: uuid.UUID) -> list[Finding]:
            return []

        async def create(self, finding: Finding) -> Finding:
            return finding

        async def update_status(self, finding_id: uuid.UUID, status: FindingStatus) -> Finding:
            raise NotImplementedError

        async def bulk_upsert_findings(
            self, repository_id: uuid.UUID, scan_run_id: uuid.UUID, findings: list[Finding]
        ) -> None:
            self.upserted.append((repository_id, scan_run_id, findings))

        async def count_by_last_seen_scan_run(self, scan_run_id: uuid.UUID) -> int:
            self.counted.append(scan_run_id)
            return len(self.counted)

    async def _run() -> None:
        repo = _FakeFindingRepository()
        repository_id = uuid.uuid4()
        scan_run_id = uuid.uuid4()
        finding = Finding(
            id=uuid.uuid4(),
            scan_task_id=uuid.uuid4(),
            severity=FindingSeverity.HIGH,
            rule_id="rule",
            title="title",
            fingerprint="fp-1",
            created_at=_NOW,
            updated_at=_NOW,
        )

        result = await repo.bulk_upsert_findings(repository_id, scan_run_id, [finding])
        assert result is None
        assert repo.upserted == [(repository_id, scan_run_id, [finding])]

        count = await repo.count_by_last_seen_scan_run(scan_run_id)
        assert count == 1
        assert repo.counted == [scan_run_id]

    asyncio.run(_run())
