"""ASGI middleware for limiting incoming request body sizes."""

from __future__ import annotations

import logging

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config.settings import get_settings
from app.security.audit import SecurityEventType, log_security_event

logger = logging.getLogger(__name__)


class RequestSizeLimitMiddleware:
    """Pure ASGI middleware that rejects oversized requests early."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """ASGI entry-point. Reject HTTP requests with oversized Content-Length."""
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request = Request(scope, receive, send)
        content_length_raw = request.headers.get("content-length")

        if content_length_raw is not None:
            try:
                content_length = int(content_length_raw)
            except ValueError:
                content_length = 0

            settings = get_settings()
            max_bytes = settings.max_request_body_bytes

            if content_length > max_bytes:
                log_security_event(
                    event_type=SecurityEventType.PAYLOAD_TOO_LARGE,
                    path=str(scope.get("path", "")),
                    method=str(scope.get("method", "")),
                    status_code=413,
                    details={
                        "content_length": content_length,
                        "max_bytes": max_bytes,
                    },
                )
                response = JSONResponse(
                    status_code=413,
                    content={
                        "error_code": "PAYLOAD_TOO_LARGE",
                        "message": (
                            f"Request body ({content_length} bytes) exceeds "
                            f"the maximum allowed size ({max_bytes} bytes)."
                        ),
                        "details": {
                            "byte_count": content_length,
                            "max_bytes": max_bytes,
                        },
                    },
                )
                await response(scope, receive, send)
                return

        await self._app(scope, receive, send)


__all__ = ["RequestSizeLimitMiddleware"]
