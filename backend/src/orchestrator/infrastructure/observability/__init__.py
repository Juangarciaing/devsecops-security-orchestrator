"""Module 13a — cross-cutting OpenTelemetry tracing bootstrap.

Off by default: nothing in this package does anything unless
`Settings.otel_exporter_otlp_endpoint` is explicitly set (D1).
"""

from __future__ import annotations
