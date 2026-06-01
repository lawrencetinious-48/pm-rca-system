from __future__ import annotations

import time
import uuid

from flask import g, request


def configure_request_observability(app, *, access_log_enabled: bool = False) -> None:
    @app.before_request
    def assign_request_context():
        g.request_started_at = time.perf_counter()
        inbound_request_id = (request.headers.get("X-Request-ID") or "").strip()
        g.request_id = inbound_request_id or uuid.uuid4().hex

    @app.after_request
    def append_request_headers(response):
        response.headers["X-Request-ID"] = getattr(g, "request_id", uuid.uuid4().hex)

        started_at = getattr(g, "request_started_at", None)
        if access_log_enabled and started_at is not None:
            duration_ms = (time.perf_counter() - started_at) * 1000
            app.logger.info(
                "request id=%s method=%s path=%s status=%s duration_ms=%.2f remote_addr=%s",
                g.request_id,
                request.method,
                request.path,
                response.status_code,
                duration_ms,
                request.remote_addr,
            )
        return response
