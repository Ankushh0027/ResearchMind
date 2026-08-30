"""Sliding-window rate limiter protocol and in-memory implementation.

Architecture notes:
- ``RateLimiterProtocol`` defines the interface so the in-memory
  implementation can be transparently replaced by a Redis-backed or
  other distributed implementation without modifying route handlers.
- ``InMemoryRateLimiter`` uses a per-key :class:`collections.deque` of
  monotonic timestamps to implement a sliding-window counter.  This
  keeps memory bounded: only timestamps within the current window are
  retained.

⚠️  DISTRIBUTED DEPLOYMENT WARNING
    ``InMemoryRateLimiter`` is PROCESS-LOCAL.  State is NOT shared across
    multiple worker processes or container instances.  For horizontally
    scaled deployments, replace this implementation with one backed by a
    shared store (e.g., Redis ``ZADD``/``ZREMRANGEBYSCORE`` pattern) that
    satisfies the ``RateLimiterProtocol`` interface.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Protocol, runtime_checkable

from fastapi import Depends, HTTPException, Request

from app.config.settings import AppSettings, get_settings
from app.security.audit import SecurityEventType, log_security_event

logger = logging.getLogger(__name__)


@runtime_checkable
class RateLimiterProtocol(Protocol):
    """Interface for rate-limiter implementations.

    Implementing this protocol allows drop-in replacement of the in-memory
    limiter with a distributed Redis-backed implementation in production
    without changes to route handlers.
    """

    def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> bool:
        """Return True if the request is within the rate limit, False otherwise."""
        ...

    def reset(self, key: str | None = None) -> None:
        """Reset rate-limit counters."""
        ...


class InMemoryRateLimiter:
    """Thread-safe sliding-window rate limiter using monotonic timestamps.

    Each unique ``key`` (typically a tenant ID or client IP address) has an
    associated :class:`~collections.deque` that stores the monotonic timestamps
    of accepted requests within the current window.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._windows: defaultdict[str, deque[float]] = defaultdict(deque)

    def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> bool:
        """Check and record a request against the sliding window."""
        now = time.monotonic()
        cutoff = now - window_seconds

        with self._lock:
            window = self._windows[key]
            # Prune expired timestamps from the left
            while window and window[0] < cutoff:
                window.popleft()

            if len(window) >= max_requests:
                return False

            window.append(now)
            return True

    def reset(self, key: str | None = None) -> None:
        """Reset the rate-limit state."""
        with self._lock:
            if key is None:
                self._windows.clear()
            else:
                self._windows.pop(key, None)


# Module-level singleton with override support for testing
_rate_limiter: RateLimiterProtocol = InMemoryRateLimiter()


def get_rate_limiter() -> RateLimiterProtocol:
    """Return the active rate-limiter instance."""
    return _rate_limiter


def set_rate_limiter(limiter: RateLimiterProtocol) -> None:
    """Override the active rate-limiter singleton (for tests)."""
    global _rate_limiter
    _rate_limiter = limiter


def _get_client_key(request: Request) -> str:
    """Extract a best-effort rate limit key identifier from the request.

    Prefers resolved ``tenant_id`` from auth state, falls back to ``X-Forwarded-For``
    or client IP.
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id and tenant_id != "default-tenant":
        return f"tenant:{tenant_id}"

    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        ip = forwarded_for.split(",")[0].strip()
        return f"ip:{ip}"

    if request.client:
        return f"ip:{request.client.host}"

    return "ip:unknown"


async def rate_limit_submissions(
    request: Request,
    settings: AppSettings = Depends(get_settings),
) -> None:
    """FastAPI dependency enforcing rate limits on submission endpoints."""
    if not settings.rate_limit_enabled:
        return

    limiter = get_rate_limiter()
    client_key = _get_client_key(request)

    allowed = limiter.is_allowed(
        key=client_key,
        max_requests=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )

    if not allowed:
        retry_after = settings.rate_limit_window_seconds
        tenant_id = getattr(request.state, "tenant_id", None)

        log_security_event(
            event_type=SecurityEventType.RATE_LIMIT_EXCEEDED,
            path=str(request.url.path),
            method=request.method,
            status_code=429,
            tenant_id=tenant_id,
            client_ip=client_key,
            details={
                "max_requests": settings.rate_limit_requests,
                "window_seconds": settings.rate_limit_window_seconds,
            },
        )

        raise HTTPException(
            status_code=429,
            detail={
                "error_code": "RATE_LIMIT_EXCEEDED",
                "message": f"Rate limit exceeded. Try again in {retry_after} seconds.",
                "retry_after_seconds": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )


__all__ = [
    "InMemoryRateLimiter",
    "RateLimiterProtocol",
    "get_rate_limiter",
    "rate_limit_submissions",
    "set_rate_limiter",
]
