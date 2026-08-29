"""Unit tests for Phase 6.5 in-memory sliding-window rate limiter.

Coverage:
1.  is_allowed — requests under threshold are permitted
2.  is_allowed — request at exactly the threshold is permitted
3.  is_allowed — request exceeding threshold is rejected
4.  reset(key) — resets state for a specific key
5.  reset(None) — resets all state
6.  Window sliding — old timestamps expire and new requests are admitted
7.  Multiple independent keys do not share state
8.  rate_limit_submissions dependency no-ops when RATE_LIMIT_ENABLED=False
9.  rate_limit_submissions raises 429 when limit exceeded (RATE_LIMIT_ENABLED=True)
10. 429 response contains Retry-After header
11. 429 response body has structured error_code RATE_LIMIT_EXCEEDED
12. Requests under limit pass through (integration with FastAPI)
13. RateLimiterProtocol isinstance check (runtime_checkable)
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.app import create_app
from app.api.service import ResearchService
from app.orchestration.router import create_default_worker_router
from app.security.rate_limiter import (
    InMemoryRateLimiter,
    RateLimiterProtocol,
    set_rate_limiter,
)

# ---------------------------------------------------------------------------
# Unit tests: InMemoryRateLimiter
# ---------------------------------------------------------------------------


class TestInMemoryRateLimiter:
    """Tests for the in-memory sliding-window rate limiter implementation."""

    def test_first_request_is_allowed(self) -> None:
        limiter = InMemoryRateLimiter()
        assert limiter.is_allowed("client1", max_requests=5, window_seconds=60) is True

    def test_requests_under_threshold_are_allowed(self) -> None:
        limiter = InMemoryRateLimiter()
        for _ in range(4):
            assert (
                limiter.is_allowed("client1", max_requests=5, window_seconds=60) is True
            )

    def test_request_at_threshold_is_allowed(self) -> None:
        limiter = InMemoryRateLimiter()
        for _ in range(5):
            limiter.is_allowed("client1", max_requests=5, window_seconds=60)
        # The 5th request should be the boundary (already consumed above)
        # Reset and test the exactly-at-limit case
        limiter.reset("client1")
        results = [
            limiter.is_allowed("client1", max_requests=3, window_seconds=60)
            for _ in range(3)
        ]
        assert all(results), "All requests at threshold should be allowed"

    def test_request_exceeding_threshold_is_rejected(self) -> None:
        limiter = InMemoryRateLimiter()
        for _ in range(3):
            limiter.is_allowed("client1", max_requests=3, window_seconds=60)
        # 4th request exceeds limit
        assert limiter.is_allowed("client1", max_requests=3, window_seconds=60) is False

    def test_reset_specific_key(self) -> None:
        limiter = InMemoryRateLimiter()
        for _ in range(5):
            limiter.is_allowed("client1", max_requests=5, window_seconds=60)
        # Exhausted
        assert limiter.is_allowed("client1", max_requests=5, window_seconds=60) is False
        # Reset only this key
        limiter.reset("client1")
        assert limiter.is_allowed("client1", max_requests=5, window_seconds=60) is True

    def test_reset_all_keys(self) -> None:
        limiter = InMemoryRateLimiter()
        for key in ["c1", "c2", "c3"]:
            for _ in range(5):
                limiter.is_allowed(key, max_requests=5, window_seconds=60)
        # All exhausted
        for key in ["c1", "c2", "c3"]:
            assert limiter.is_allowed(key, max_requests=5, window_seconds=60) is False
        limiter.reset()  # reset all
        for key in ["c1", "c2", "c3"]:
            assert limiter.is_allowed(key, max_requests=5, window_seconds=60) is True

    def test_independent_keys_do_not_share_state(self) -> None:
        limiter = InMemoryRateLimiter()
        for _ in range(3):
            limiter.is_allowed("clientA", max_requests=3, window_seconds=60)
        # clientA is exhausted; clientB should be unaffected
        assert limiter.is_allowed("clientA", max_requests=3, window_seconds=60) is False
        assert limiter.is_allowed("clientB", max_requests=3, window_seconds=60) is True

    def test_expired_timestamps_slide_out(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Timestamps older than window_seconds should be pruned, allowing new requests."""
        limiter = InMemoryRateLimiter()
        # Exhaust limit at current time
        for _ in range(3):
            limiter.is_allowed("client1", max_requests=3, window_seconds=10)
        assert limiter.is_allowed("client1", max_requests=3, window_seconds=10) is False

        # Advance monotonic time by 11 seconds so all timestamps expire
        original_time = time.monotonic
        start = original_time()
        monkeypatch.setattr(time, "monotonic", lambda: start + 11.0)

        # Window has slid; new request should be allowed
        assert limiter.is_allowed("client1", max_requests=3, window_seconds=10) is True

    def test_protocol_isinstance_check(self) -> None:
        """InMemoryRateLimiter satisfies RateLimiterProtocol at runtime."""
        limiter = InMemoryRateLimiter()
        assert isinstance(limiter, RateLimiterProtocol)

    def test_reset_nonexistent_key_is_safe(self) -> None:
        """Resetting a key that doesn't exist should not raise."""
        limiter = InMemoryRateLimiter()
        limiter.reset("ghost-key")  # Should not raise


# ---------------------------------------------------------------------------
# Integration tests: rate_limit_submissions dependency via FastAPI
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    from app.config.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _make_rate_limited_app(
    monkeypatch: pytest.MonkeyPatch,
    *,
    max_requests: int = 3,
    window_seconds: int = 60,
) -> tuple[FastAPI, InMemoryRateLimiter]:
    """Configure app with rate limiting enabled and return (app, limiter)."""
    monkeypatch.setenv("API_AUTH_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", str(max_requests))
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", str(window_seconds))
    from app.config.settings import get_settings

    get_settings.cache_clear()

    limiter = InMemoryRateLimiter()
    set_rate_limiter(limiter)

    service = ResearchService(router=create_default_worker_router(), max_concurrency=2)
    app = create_app(service=service)
    return app, limiter


@pytest.fixture(autouse=True)
def _restore_default_rate_limiter() -> Iterator[None]:
    """Restore the module-level rate limiter singleton after each test."""
    from app.security.rate_limiter import InMemoryRateLimiter, set_rate_limiter

    yield
    set_rate_limiter(InMemoryRateLimiter())


@pytest.mark.asyncio
async def test_rate_limit_disabled_allows_many_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When RATE_LIMIT_ENABLED=false, unlimited requests are allowed."""
    monkeypatch.setenv("API_AUTH_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    from app.config.settings import get_settings

    get_settings.cache_clear()
    service = ResearchService(router=create_default_worker_router(), max_concurrency=2)
    app = create_app(service=service)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        for _ in range(5):
            resp = await client.post(
                "/api/v1/runs", json={"query": "rate limit disabled test"}
            )
            assert resp.status_code == 201


@pytest.mark.asyncio
async def test_rate_limit_allows_requests_under_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Requests under the configured limit succeed with HTTP 201."""
    app, limiter = _make_rate_limited_app(monkeypatch, max_requests=3)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        for _ in range(3):
            resp = await client.post(
                "/api/v1/runs", json={"query": "within limit request"}
            )
            assert resp.status_code == 201


@pytest.mark.asyncio
async def test_rate_limit_rejects_over_threshold_with_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Request exceeding the limit → HTTP 429."""
    app, limiter = _make_rate_limited_app(monkeypatch, max_requests=2)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Exhaust the limit
        for _ in range(2):
            await client.post("/api/v1/runs", json={"query": "within"})
        # Next request should be rate-limited
        resp = await client.post("/api/v1/runs", json={"query": "over limit"})
    assert resp.status_code == 429


@pytest.mark.asyncio
async def test_rate_limit_429_has_retry_after_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """429 response includes Retry-After header."""
    app, limiter = _make_rate_limited_app(
        monkeypatch, max_requests=1, window_seconds=30
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post("/api/v1/runs", json={"query": "first"})
        resp = await client.post("/api/v1/runs", json={"query": "second"})
    assert resp.status_code == 429
    assert "retry-after" in resp.headers
    assert int(resp.headers["retry-after"]) == 30


@pytest.mark.asyncio
async def test_rate_limit_429_body_has_structured_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """429 response body is a structured ErrorResponse-compatible JSON."""
    app, limiter = _make_rate_limited_app(monkeypatch, max_requests=1)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post("/api/v1/runs", json={"query": "first"})
        resp = await client.post("/api/v1/runs", json={"query": "second"})
    assert resp.status_code == 429
    body = resp.json()
    assert body["error_code"] == "RATE_LIMIT_EXCEEDED"
    assert "message" in body


@pytest.mark.asyncio
async def test_rate_limit_reset_allows_new_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After resetting the limiter, previously exhausted clients can make requests again."""
    app, limiter = _make_rate_limited_app(monkeypatch, max_requests=1)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post("/api/v1/runs", json={"query": "first"})
        assert (
            await client.post("/api/v1/runs", json={"query": "second"})
        ).status_code == 429

        # Reset all keys — simulates window expiry
        limiter.reset()

        resp = await client.post("/api/v1/runs", json={"query": "after reset"})
        assert resp.status_code == 201
