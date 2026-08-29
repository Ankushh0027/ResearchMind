"""ASGI middleware for limiting incoming request body sizes.

Motivation:
    Without an early size check, a malicious or accidental oversized payload
    would be fully buffered into memory before FastAPI/Pydantic validation
    executes.  Checking the ``Content-Length`` header at the ASGI boundary
    lets us reject abusive payloads cheaply before any body parsing occurs.

Limitations:
    ``Content-Length`` can be omitted or spoofed by clients.  This middleware
    trusts the declared header as a first-pass guard.  For full streaming
    protection, a reverse proxy (Nginx, Cloud Run) should also enforce body
    limits, which is noted in the Phase 6.5 documentation.
"""

from __future__ import annotations

import logging

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config.settings import get_settings

logger = logging.getLogger(__name__)


class RequestSizeLimitMiddleware:
    """Pure ASGI middleware that rejects oversized requests early.

    Checks the ``Content-Length`` request header before the request is
    dispatched to FastAPI.  Requests whose declared size exceeds
    ``settings.max_request_body_bytes`` are rejected with HTTP 413 and a
    structured JSON body.

    Unlike :class:`starlette.middleware.base.BaseHTTPMiddleware` this is
    implemented as a raw ASGI callable so it fires before body parsing begins,
    keeping memory overhead minimal.

    Usage::

        app.add_middleware(RequestSizeLimitMiddleware)
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """ASGI entry-point.  Reject HTTP requests with oversized Content-Length."""
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
                logger.warning(
                    "Request rejected: payload too large",
                    extra={
                        "content_length": content_length,
                        "max_bytes": max_bytes,
                        "path": scope.get("path", ""),
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
