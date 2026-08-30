"""ASGI middleware for attaching standard HTTP security headers.

Headers applied on every response:
- ``X-Content-Type-Options: nosniff``        — prevent MIME-type sniffing
- ``X-Frame-Options: DENY``                  — prevent clickjacking
- ``Referrer-Policy: strict-origin-when-cross-origin``
- ``X-XSS-Protection: 0``                   — disable legacy XSS filter (modern browsers)
- ``Content-Security-Policy``               — permissive policy safe for Swagger/OpenAPI docs
- ``Cache-Control: no-store, max-age=0``    — attached to API endpoint responses to prevent client/proxy caching
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: https:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "object-src 'none'; "
    "base-uri 'self';"
)

_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-XSS-Protection": "0",
    "Content-Security-Policy": _CSP,
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that appends standard HTTP security headers to all responses."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Attach security headers to the outgoing response."""
        response: Response = await call_next(request)
        for header, value in _SECURITY_HEADERS.items():
            response.headers[header] = value

        # Attach anti-caching header to API endpoints (avoiding breaking SSE streams which use no-cache)
        if (
            request.url.path.startswith("/api/v1/")
            and "Cache-Control" not in response.headers
        ):
            response.headers["Cache-Control"] = "no-store, max-age=0"

        return response


__all__ = [
    "SecurityHeadersMiddleware",
    "_SECURITY_HEADERS",
]
