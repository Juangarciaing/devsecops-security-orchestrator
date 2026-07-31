"""realtime-push PR1 — Redis pub/sub -> SSE relay for scan status updates.

Off by default: nothing in this package does anything unless
`Settings.realtime_enabled` is explicitly set (design D-Gate). Mirrors the
`infrastructure/observability/` package shape (Module 13a precedent).
"""

from __future__ import annotations
