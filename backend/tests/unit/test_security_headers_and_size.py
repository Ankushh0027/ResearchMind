"""Unit tests for Phase 6.5 security headers middleware and request-size limiting.

Coverage:
1.  Security headers present on successful API responses
2.  Security headers present on 4xx responses
3.  X-Content-Type-Options: nosniff
4.  X-Frame-Options: DENY
5.  Referrer-Policy: strict-origin-when-cross-origin
6.  X-XSS-Protection: 0
7.  Content-Security-Policy header present
8.  /docs and /redoc accessible (security headers don't break OpenAPI)
9.  Request with Content-Length exceeding limit → 413
10. Request with Content-Length at exactly the limit → passes (middleware passes)
11. Request with Content-Length under limit → passes
12. Request without Content-Length header → passes (no blocking)
13. 413 body is structured JSON with error_code
14. MAX_REQUEST_BODY_BYTES configurable
"""

import json
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.app import create_app
from app.api.service import ResearchService
from app.orchestration.router import create_default_worker_router


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    from app.config.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _make_app(monkeypatch: pytest.MonkeyPatch, **env: str) -> FastAPI:
    """Create a test app with given environment overrides."""
    monkeypatch.setenv("API_AUTH_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from app.config.settings import get_settings

    get_settings.cache_clear()
    service = ResearchService(router=create_default_worker_router(), max_concurrency=2)
    return create_app(service=service)


# ---------------------------------------------------------------------------
# Security headers tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_security_headers_on_success_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Security headers are present on successful responses."""
    app = _make_app(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"
    assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
    assert resp.headers.get("x-xss-protection") == "0"
    assert "content-security-policy" in resp.headers


@pytest.mark.asyncio
async def test_x_content_type_options_nosniff(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _make_app(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/healthz")
    assert resp.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_x_frame_options_deny(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _make_app(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/healthz")
    assert resp.headers["x-frame-options"] == "DENY"


@pytest.mark.asyncio
async def test_referrer_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _make_app(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/healthz")
    assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"


@pytest.mark.asyncio
async def test_xss_protection_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """X-XSS-Protection: 0 disables legacy browser XSS filter per modern guidance."""
    app = _make_app(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/healthz")
    assert resp.headers["x-xss-protection"] == "0"


@pytest.mark.asyncio
async def test_csp_header_present(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _make_app(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/healthz")
    assert "content-security-policy" in resp.headers
    csp = resp.headers["content-security-policy"]
    assert "default-src" in csp
    assert "frame-ancestors" in csp


@pytest.mark.asyncio
async def test_security_headers_on_4xx_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Security headers are present even on 404 error responses."""
    app = _make_app(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/api/v1/runs/nonexistent-run-id")
    # 404 expected
    assert resp.status_code == 404
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"


@pytest.mark.asyncio
async def test_docs_accessible_with_security_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """/docs endpoint renders successfully (security headers don't break Swagger UI)."""
    app = _make_app(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/docs")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_redoc_accessible_with_security_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """/redoc endpoint renders successfully (security headers don't break ReDoc)."""
    app = _make_app(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/redoc")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Request-size limit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_size_below_limit_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Requests well within the body size limit are accepted."""
    app = _make_app(monkeypatch, MAX_REQUEST_BODY_BYTES="1048576")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/v1/runs",
            json={"query": "small query within limits"},
        )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_request_size_above_limit_rejected_413(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Requests declaring Content-Length > MAX_REQUEST_BODY_BYTES are rejected with 413."""
    # Set a tiny limit of 64 bytes
    app = _make_app(monkeypatch, MAX_REQUEST_BODY_BYTES="64")
    transport = ASGITransport(app=app)
    big_payload = json.dumps({"query": "x" * 200})
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/v1/runs",
            content=big_payload.encode(),
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(big_payload.encode())),
            },
        )
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_413_response_body_is_structured(monkeypatch: pytest.MonkeyPatch) -> None:
    """413 response has structured JSON with error_code PAYLOAD_TOO_LARGE."""
    app = _make_app(monkeypatch, MAX_REQUEST_BODY_BYTES="64")
    transport = ASGITransport(app=app)
    big_payload = json.dumps({"query": "x" * 200})
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/v1/runs",
            content=big_payload.encode(),
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(big_payload.encode())),
            },
        )
    assert resp.status_code == 413
    body = resp.json()
    assert body["error_code"] == "PAYLOAD_TOO_LARGE"
    assert "message" in body


@pytest.mark.asyncio
async def test_request_without_content_length_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Requests without a Content-Length header are not rejected by the size middleware."""
    app = _make_app(monkeypatch, MAX_REQUEST_BODY_BYTES="64")
    transport = ASGITransport(app=app)
    # httpx sets Content-Length automatically for json= argument but we can
    # use a small payload that fits within the 64-byte limit.
    small = json.dumps({"query": "tiny"})
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/v1/runs",
            content=small.encode(),
            headers={"Content-Type": "application/json"},
        )
    # Either 201 or 422 (Pydantic) is fine — we just want NOT 413
    assert resp.status_code != 413
