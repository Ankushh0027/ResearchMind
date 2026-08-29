"""API-key authentication dependency for FastAPI endpoints.

Design notes:
- Constant-time key comparison via ``secrets.compare_digest`` prevents
  timing-based secret oracle attacks.
- Authentication is gated by ``API_AUTH_ENABLED`` so unit tests and local
  development remain fully deterministic without requiring a real key.
- Raw API keys are never logged, never echoed in error messages, and never
  stored beyond the comparison call.
- Preferred header: ``Authorization: Bearer <API_KEY>``
  Fallback header:  ``X-API-Key: <API_KEY>``
"""

from __future__ import annotations

import logging
import secrets

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config.settings import AppSettings, get_settings

logger = logging.getLogger(__name__)

# HTTPBearer extracts the Bearer token from the Authorization header.
# auto_error=False lets us return a structured 401 instead of the default 403.
_bearer_scheme = HTTPBearer(auto_error=False)


def validate_api_key_constant_time(provided_key: str, expected_key: str) -> bool:
    """Compare two API keys in constant time to prevent timing attacks.

    Uses :func:`secrets.compare_digest` which takes O(n) time regardless of
    whether the keys share a common prefix.  Both arguments are encoded to
    bytes so the function works with string inputs as required by the
    stdlib implementation.

    Args:
        provided_key: The key supplied by the API caller.
        expected_key: The configured server-side key.

    Returns:
        ``True`` if the keys are identical, ``False`` otherwise.
    """
    if not provided_key or not expected_key:
        # Perform a dummy comparison to keep constant-time property even when
        # one side is empty, then return False.
        secrets.compare_digest(b"", b"")
        return False
    try:
        return secrets.compare_digest(
            provided_key.encode("utf-8"),
            expected_key.encode("utf-8"),
        )
    except Exception:
        return False


async def verify_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    settings: AppSettings = Depends(get_settings),
) -> None:
    """FastAPI dependency enforcing API-key authentication.

    When ``API_AUTH_ENABLED`` is ``False`` (default), this dependency is a
    no-op so that existing integration tests and local development work
    without credentials.

    When ``API_AUTH_ENABLED`` is ``True``:
    - Extracts the key from ``Authorization: Bearer <token>``.
    - Falls back to the ``X-API-Key`` header if the Bearer header is absent.
    - Compares the provided key against the configured ``API_KEY`` using
      constant-time comparison.
    - Raises HTTP 401 with a structured error body if authentication fails.
    - Logs authentication failures at WARN level without revealing the key.

    Args:
        request: The incoming FastAPI/Starlette request.
        credentials: Extracted HTTPBearer credentials (may be ``None``).
        settings: Injected application settings.

    Raises:
        HTTPException: HTTP 401 when authentication is enabled and fails.
    """
    if not settings.api_auth_enabled:
        return

    # 1. Prefer the Authorization: Bearer header
    provided_key: str | None = None
    if credentials is not None:
        provided_key = credentials.credentials

    # 2. Fallback: X-API-Key header
    if not provided_key:
        provided_key = request.headers.get("X-API-Key")

    if not provided_key:
        logger.warning(
            "API authentication failed: no credentials provided",
            extra={"path": str(request.url.path), "method": request.method},
        )
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "UNAUTHORIZED",
                "message": "Authentication required. "
                "Provide a valid API key in the Authorization: Bearer header.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not validate_api_key_constant_time(provided_key, settings.api_key):
        logger.warning(
            "API authentication failed: invalid key presented",
            extra={"path": str(request.url.path), "method": request.method},
        )
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "UNAUTHORIZED",
                "message": "Invalid API key.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )


__all__ = [
    "validate_api_key_constant_time",
    "verify_api_key",
]
