"""In-memory test doubles for framework-free domain ports.

CI/unit tests do not reliably have Docker socket access — modules that
depend on `ContainerRunnerPort` (Module 6+) script `FakeContainerRunner`
instead of hitting a real Docker daemon.
"""

from __future__ import annotations
