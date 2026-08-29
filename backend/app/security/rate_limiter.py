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

logger = logging.getLogger(__name__)


@runtime_checkable
class RateLimiterProtocol(Protocol):
    """Interface for rate-limiter implementations.

    Implementing this protocol allows drop-in replacement of the in-memory
    limiter with a distributed Redis-backed implementation in production
    without changes to route handlers.
    """

    def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> bool:
        """Return True if the request is within the rate limit, False otherwise.

        Args:
            key: Client identifier (e.g., IP address, API key prefix).
            max_requests: Maximum number of requests allowed in the window.
            window_seconds: Rolling window duration in seconds.

        Returns:
            ``True`` if the request should be allowed, ``False`` if it should
            be rejected with HTTP 429.
        """
        ...

    def reset(self, key: str | None = None) -> None:
        """Reset rate-limit counters.

        Args:
            key: If provided, reset only this key.  If ``None``, reset all.
        """
        ...


class InMemoryRateLimiter:
    """Thread-safe sliding-window rate limiter using monotonic timestamps.

    Each unique ``key`` (typically a client IP address) has an associated
    :class:`~collections.deque` that stores the monotonic timestamps of
    accepted requests within the current window.  On each call to
    :meth:`is_allowed`, stale timestamps (older than ``window_seconds``)
    are pruned before deciding whether to accept the new request.

    ⚠️  This implementation is PROCESS-LOCAL.  It is suitable for:
    - Single-instance deployments.
    - Unit and integration test environments.

    It is NOT suitable for:
    - Horizontally scaled multi-instance deployments.
    - Containers behind a load balancer with shared rate-limit state.
    For those scenarios, implement ``RateLimiterProtocol`` with a
    Redis-backed or equivalent distributed store.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        # key -> deque of monotonic timestamps (float, seconds)
        self._windows: defaultdict[str, deque[float]] = defaultdict(deque)

    def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> bool:
        """Check and record a request against the sliding window.

        Args:
            key: Client identifier string.
            max_requests: Maximum requests in the window.
            window_seconds: Window size in seconds.

        Returns:
            ``True`` if the request is within the limit, ``False`` otherwise.
        """
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
        """Reset the rate-limit state.

        Args:
            key: Specific client key to reset, or ``None`` to reset all.
        """
        with self._lock:
            if key is None:
                self._windows.clear()
            else:
                self._windows.pop(key, None)


# ---------------------------------------------------------------------------
# Module-level singleton with override support for testing
# ---------------------------------------------------------------------------

_rate_limiter: RateLimiterProtocol = InMemoryRateLimiter()


def get_rate_limiter() -> RateLimiterProtocol:
    """Return the active rate-limiter instance (module-level singleton).

    In production: returns the default ``InMemoryRateLimiter``.
    In tests: can be overridden via :func:`set_rate_limiter` to inject a
    custom implementation without patching the module directly.
    """
    return _rate_limiter


def set_rate_limiter(limiter: RateLimiterProtocol) -> None:
    """Override the active rate-limiter singleton.

    Intended for test setup so deterministic custom implementations can be
    injected without modifying production code paths.

    Args:
        limiter: A ``RateLimiterProtocol``-conforming instance.
    """
    global _rate_limiter
    _rate_limiter = limiter


def _get_client_key(request: Request) -> str:
    """Extract a best-effort client identifier from the request.

    Prefers ``X-Forwarded-For`` (first hop) for deployments behind a
    reverse proxy, then falls back to the direct client IP.

    Args:
        request: The incoming Starlette request.

    Returns:
        A string key uniquely identifying the client.
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


async def rate_limit_submissions(
    request: Request,
    settings: AppSettings = Depends(get_settings),
) -> None:
    """FastAPI dependency enforcing rate limits on submission endpoints.

    When ``RATE_LIMIT_ENABLED`` is ``False`` (default), this is a no-op.

    When ``RATE_LIMIT_ENABLED`` is ``True``:
    - Identifies the client by IP (with X-Forwarded-For support).
    - Checks the sliding-window counter against configured limits.
    - Returns HTTP 429 with ``Retry-After`` header if the limit is exceeded.

    ⚠️  The underlying ``InMemoryRateLimiter`` is PROCESS-LOCAL.
    Limits are NOT enforced globally across multiple instances.

    Args:
        request: The incoming FastAPI request.
        settings: Injected application settings.

    Raises:
        HTTPException: HTTP 429 when rate limit is exceeded.
    """
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
        logger.warning(
            "Rate limit exceeded",
            extra={"client_key": client_key, "path": str(request.url.path)},
        )
        raise HTTPException(
            status_code=429,
            detail={
                "error_code": "RATE_LIMIT_EXCEEDED",
                "message": (
                    f"Rate limit exceeded. Try again in {retry_after} seconds."
                ),
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
