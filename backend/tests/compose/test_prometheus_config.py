"""Compose contracts for the opt-in internal Prometheus topology."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[3]


def _compose_config(*, observability: bool = False, base_only: bool = True) -> dict[str, Any]:
    command = ["docker", "compose"]
    if base_only:
        command.extend(["-f", "docker-compose.yml"])
    if observability:
        command.extend(["--profile", "observability"])
    command.extend(["config", "--format", "json"])
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_observability_profile_is_internal_and_orders_metric_initialization() -> None:
    config = _compose_config(observability=True)
    services = config["services"]
    prometheus = services["prometheus"]
    worker_exporter = services["worker-metrics"]

    assert prometheus["profiles"] == ["observability"]
    assert "ports" not in prometheus
    assert prometheus["volumes"] == [
        {
            "type": "bind",
            "source": str(ROOT / "docker" / "prometheus" / "prometheus.yml"),
            "target": "/etc/prometheus/prometheus.yml",
            "read_only": True,
            "bind": {},
        }
    ]
    assert prometheus["depends_on"]["backend"]["condition"] == "service_healthy"
    assert (
        worker_exporter["depends_on"]["metrics-init"]["condition"]
        == "service_completed_successfully"
    )
    assert ".initialized" in services["metrics-init"]["command"][2]


def test_metrics_have_only_prometheus_scrape_access_and_no_host_ports() -> None:
    config = _compose_config(observability=True)
    services = config["services"]
    backend = services["backend"]
    proxy = services["proxy"]
    prometheus = services["prometheus"]

    assert "ports" not in backend
    assert proxy["ports"] == [
        {"mode": "ingress", "target": 8080, "published": "8000", "protocol": "tcp"}
    ]
    assert set(prometheus["networks"]) == {"observability"}
    assert "observability" not in services["frontend"]["networks"]
    assert "return 404" in (ROOT / "docker" / "metrics-proxy.nginx.conf").read_text()


def test_profile_off_keeps_prometheus_services_out_of_the_base_stack() -> None:
    services = _compose_config()["services"]

    assert "prometheus" not in services
    assert "worker-metrics" not in services
    assert {"backend", "worker", "proxy"}.issubset(services)


def test_development_override_preserves_the_private_api_bind_address() -> None:
    backend_command = _compose_config(base_only=False)["services"]["backend"]["command"]

    assert "172.30.0.10" in backend_command
    assert "0.0.0.0" not in backend_command
