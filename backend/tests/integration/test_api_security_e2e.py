"""Integration tests for Phase 6.5 API security — end-to-end HTTP scenarios.

Coverage:
1.  Missing API key → 401 (auth enabled)
2.  Invalid API key → 401 (auth enabled)
3.  Valid API key → 201 created (auth enabled)
4.  Constant-time comparison path is exercised
5.  Public /healthz accessible without credentials (auth enabled)
6.  Allowed CORS origin receives Access-Control-Allow-Origin header
7.  Disallowed CORS origin is rejected (no ACAO header)
8.  Rate limit allows requests under threshold
9.  Rate limit rejects requests over threshold → 429
10. Rate limit state reset restores access
11. Oversized request body → 413
12. Request with max_length violation on query field → 422
13. Security headers present on all responses
14. No raw API keys appear in 401/429 error responses
15. Existing test infrastructure (unauthenticated) remains deterministic
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.app import create_app
from app.api.service import ResearchService
from app.orchestration.router import create_default_worker_router
from app.security.rate_limiter import InMemoryRateLimiter, set_rate_limiter

VALID_KEY = "integration-test-secret-key-xyz"


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    from app.config.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _restore_rate_limiter() -> Iterator[None]:
    yield
    set_rate_limiter(InMemoryRateLimiter())


def _make_app(
    monkeypatch: pytest.MonkeyPatch,
    *,
    auth_enabled: bool = False,
    rate_limit_enabled: bool = False,
    max_requests: int = 60,
    window_seconds: int = 60,
    cors_origins: str = "http://allowed.example.com,http://localhost:3000",
    max_request_body_bytes: int = 1_048_576,
    max_goal_length: int = 4000,
) -> FastAPI:
    """Create a test FastAPI app with specified security configuration."""
    monkeypatch.setenv("API_AUTH_ENABLED", str(auth_enabled).lower())
    monkeypatch.setenv("API_KEY", VALID_KEY)
    monkeypatch.setenv("RATE_LIMIT_ENABLED", str(rate_limit_enabled).lower())
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", str(max_requests))
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", str(window_seconds))
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", cors_origins)
    monkeypatch.setenv("MAX_REQUEST_BODY_BYTES", str(max_request_body_bytes))
    monkeypatch.setenv("MAX_RESEARCH_GOAL_LENGTH", str(max_goal_length))
    from app.config.settings import get_settings

    get_settings.cache_clear()
    service = ResearchService(router=create_default_worker_router(), max_concurrency=2)
    return create_app(service=service)


# ---------------------------------------------------------------------------
# 1-5: Authentication tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_missing_api_key_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test 1: Missing API key → 401."""
    app = _make_app(monkeypatch, auth_enabled=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post("/api/v1/runs", json={"query": "test"})
    assert resp.status_code == 401
    body = resp.json()
    assert "error_code" in body
    assert body["error_code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_e2e_invalid_api_key_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test 2: Invalid API key → 401."""
    app = _make_app(monkeypatch, auth_enabled=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/v1/runs",
            json={"query": "test"},
            headers={"Authorization": "Bearer wrong-key-abc"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_e2e_valid_api_key_returns_201(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test 3: Valid API key → request accepted (201 Created)."""
    app = _make_app(monkeypatch, auth_enabled=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/v1/runs",
            json={"query": "valid authenticated research request"},
            headers={"Authorization": f"Bearer {VALID_KEY}"},
        )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_e2e_constant_time_comparison_path_exercised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test 4: Constant-time comparison is used (secrets.compare_digest called)."""
    import secrets

    compare_calls: list[bool] = []
    original = secrets.compare_digest

    def tracking_compare(a: bytes, b: bytes) -> bool:
        result = original(a, b)
        compare_calls.append(result)
        return result

    monkeypatch.setattr(secrets, "compare_digest", tracking_compare)
    app = _make_app(monkeypatch, auth_enabled=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post(
            "/api/v1/runs",
            json={"query": "test"},
            headers={"Authorization": f"Bearer {VALID_KEY}"},
        )
    assert len(compare_calls) >= 1, "secrets.compare_digest was not called"


@pytest.mark.asyncio
async def test_e2e_health_accessible_without_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test 5: /healthz is public even with auth enabled."""
    app = _make_app(monkeypatch, auth_enabled=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 6-7: CORS tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_allowed_cors_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test 6: CORS preflight from allowed origin receives Access-Control-Allow-Origin."""
    app = _make_app(
        monkeypatch,
        cors_origins="http://allowed.example.com,http://localhost:3000",
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.options(
            "/api/v1/runs",
            headers={
                "Origin": "http://allowed.example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
    acao = resp.headers.get("access-control-allow-origin", "")
    assert "allowed.example.com" in acao or acao == "http://allowed.example.com"


@pytest.mark.asyncio
async def test_e2e_disallowed_cors_origin_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test 7: CORS preflight from disallowed origin does not receive ACAO header."""
    app = _make_app(
        monkeypatch,
        cors_origins="http://allowed.example.com",
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.options(
            "/api/v1/runs",
            headers={
                "Origin": "http://evil.attacker.com",
                "Access-Control-Request-Method": "POST",
            },
        )
    acao = resp.headers.get("access-control-allow-origin", "")
    assert "evil.attacker.com" not in acao
    assert acao != "*"


# ---------------------------------------------------------------------------
# 8-10: Rate limiting tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_rate_limit_under_threshold_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test 8: Requests under the rate limit are allowed."""
    limiter = InMemoryRateLimiter()
    set_rate_limiter(limiter)
    app = _make_app(monkeypatch, rate_limit_enabled=True, max_requests=5)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        for _ in range(5):
            resp = await client.post("/api/v1/runs", json={"query": "under limit"})
            assert resp.status_code == 201


@pytest.mark.asyncio
async def test_e2e_rate_limit_over_threshold_returns_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test 9: Requests exceeding the rate limit → 429 Too Many Requests."""
    limiter = InMemoryRateLimiter()
    set_rate_limiter(limiter)
    app = _make_app(monkeypatch, rate_limit_enabled=True, max_requests=2)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        for _ in range(2):
            await client.post("/api/v1/runs", json={"query": "within"})
        resp = await client.post("/api/v1/runs", json={"query": "over"})
    assert resp.status_code == 429


@pytest.mark.asyncio
async def test_e2e_rate_limit_reset_restores_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test 10: After rate limit reset, client can make new requests."""
    limiter = InMemoryRateLimiter()
    set_rate_limiter(limiter)
    app = _make_app(monkeypatch, rate_limit_enabled=True, max_requests=1)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post("/api/v1/runs", json={"query": "first"})
        assert (
            await client.post("/api/v1/runs", json={"query": "second"})
        ).status_code == 429

        limiter.reset()

        resp = await client.post("/api/v1/runs", json={"query": "after reset"})
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# 11-12: Request size and input validation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_oversized_request_body_rejected_413(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test 11: Request body exceeding MAX_REQUEST_BODY_BYTES → 413."""
    import json as _json

    app = _make_app(monkeypatch, max_request_body_bytes=128)
    transport = ASGITransport(app=app)
    big = _json.dumps({"query": "q" * 500})
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/v1/runs",
            content=big.encode(),
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(big.encode())),
            },
        )
    assert resp.status_code == 413
    body = resp.json()
    assert body["error_code"] == "PAYLOAD_TOO_LARGE"


@pytest.mark.asyncio
async def test_e2e_oversized_research_goal_rejected_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test 12: Research goal exceeding MAX_RESEARCH_GOAL_LENGTH → 422."""
    app = _make_app(monkeypatch, max_goal_length=50)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/v1/runs",
            json={"query": "x" * 100},
        )
    assert resp.status_code == 422
    body = resp.json()
    assert body["error_code"] in ("VALIDATION_ERROR",)


# ---------------------------------------------------------------------------
# 13: Security headers integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_security_headers_present_on_all_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test 13: Security headers are present on a variety of endpoint responses."""
    app = _make_app(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        endpoints = [
            ("GET", "/healthz"),
            ("GET", "/api/v1/runs/nonexistent"),
        ]
        for method, path in endpoints:
            resp = await client.request(method, path)
            assert resp.headers.get("x-content-type-options") == "nosniff", (
                f"Missing x-content-type-options on {method} {path}"
            )
            assert resp.headers.get("x-frame-options") == "DENY", (
                f"Missing x-frame-options on {method} {path}"
            )


# ---------------------------------------------------------------------------
# 14: Secret leakage check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_no_api_key_in_error_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test 14: Error responses do not contain the raw API key."""
    app = _make_app(monkeypatch, auth_enabled=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Missing key
        resp1 = await client.post("/api/v1/runs", json={"query": "test"})
        assert VALID_KEY not in resp1.text

        # Invalid key
        resp2 = await client.post(
            "/api/v1/runs",
            json={"query": "test"},
            headers={"Authorization": "Bearer incorrect-key"},
        )
        assert VALID_KEY not in resp2.text
        assert "incorrect-key" not in resp2.text


# ---------------------------------------------------------------------------
# 15: Existing unauthenticated test infrastructure remains deterministic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_existing_api_contract_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test 15: Existing API contracts are unchanged when auth and rate limiting are disabled."""
    app = _make_app(monkeypatch, auth_enabled=False, rate_limit_enabled=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Health check
        health = await client.get("/healthz")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        # Submission
        create = await client.post(
            "/api/v1/runs",
            json={"query": "deterministic test query for regression"},
        )
        assert create.status_code == 201
        data = create.json()
        assert "run_id" in data
        assert data["run_id"].startswith("run_")

        # Status lookup
        run_id = data["run_id"]
        detail = await client.get(f"/api/v1/runs/{run_id}")
        assert detail.status_code == 200

        # Non-existent run
        missing = await client.get("/api/v1/runs/does-not-exist")
        assert missing.status_code == 404
        assert missing.json()["error_code"] == "NOT_FOUND"
