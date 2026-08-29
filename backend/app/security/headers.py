"""ASGI middleware for attaching standard HTTP security headers.

Headers applied on every response:
- ``X-Content-Type-Options: nosniff``        — prevent MIME-type sniffing
- ``X-Frame-Options: DENY``                  — prevent clickjacking
- ``Referrer-Policy: strict-origin-when-cross-origin``
- ``X-XSS-Protection: 0``                   — disable legacy XSS filter (modern browsers)
- ``Content-Security-Policy``               — permissive policy safe for Swagger/OpenAPI docs

The CSP is intentionally relaxed on ``script-src`` and ``style-src`` to
allow FastAPI's built-in ``/docs`` (Swagger UI) and ``/redoc`` pages to
render correctly.  Tightening CSP further would require hosting Swagger
assets locally and is outside the hackathon scope.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# A CSP that allows Swagger UI and ReDoc to function while blocking
# obviously dangerous inline behaviour.
_CSP = (
    "default-src 'self'; "
    # Swagger UI loads scripts from cdn.jsdelivr.net
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    # Swagger UI loads fonts and styles from cdn.jsdelivr.net
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: https:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "object-src 'none'; "
    "base-uri 'self';"
)

# Security headers attached to every response.
_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-XSS-Protection": "0",
    "Content-Security-Policy": _CSP,
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that appends standard HTTP security headers to all responses.

    Designed to be safe for FastAPI applications that serve ``/docs``,
    ``/redoc``, and ``/openapi.json`` alongside REST endpoints.

    Usage::

        app.add_middleware(SecurityHeadersMiddleware)
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Attach security headers to the outgoing response."""
        response: Response = await call_next(request)
        for header, value in _SECURITY_HEADERS.items():
            response.headers[header] = value
        return response


__all__ = [
    "SecurityHeadersMiddleware",
    "_SECURITY_HEADERS",
]
