"""Internal-only HTTP exposition for Celery's prefork metric registry."""

from __future__ import annotations

import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from orchestrator.infrastructure.observability.metrics import build_worker_scrape_registry

logger = logging.getLogger(__name__)


class _MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/metrics":
            self.send_error(404)
            return
        try:
            payload = generate_latest(build_worker_scrape_registry())
        except Exception:
            logger.exception("worker metrics collection failed")
            self.send_error(500)
            return
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPE_LATEST)
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> None:
    ThreadingHTTPServer(("0.0.0.0", 9100), _MetricsHandler).serve_forever()


if __name__ == "__main__":
    main()
