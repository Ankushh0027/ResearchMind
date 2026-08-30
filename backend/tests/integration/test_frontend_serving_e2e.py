"""Integration tests for Phase 7.3 frontend static serving and API contract preservation."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
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


@pytest.mark.asyncio
async def test_frontend_root_serves_index_html(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET / serves frontend index.html when SERVE_FRONTEND=true."""
    monkeypatch.setenv("SERVE_FRONTEND", "true")
    from app.config.settings import get_settings

    get_settings.cache_clear()

    service = ResearchService(router=create_default_worker_router(), max_concurrency=2)
    app = create_app(service=service)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert "ResearchMind" in resp.text
        assert "app-container" in resp.text


@pytest.mark.asyncio
async def test_frontend_static_assets_served(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /css/styles.css and /js/app.js return 200 with appropriate content types."""
    monkeypatch.setenv("SERVE_FRONTEND", "true")
    from app.config.settings import get_settings

    get_settings.cache_clear()

    service = ResearchService(router=create_default_worker_router(), max_concurrency=2)
    app = create_app(service=service)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        css_resp = await client.get("/css/styles.css")
        assert css_resp.status_code == 200
        assert "text/css" in css_resp.headers.get("content-type", "")
        assert "--bg-primary" in css_resp.text

        js_resp = await client.get("/js/app.js")
        assert js_resp.status_code == 200
        assert "javascript" in js_resp.headers.get("content-type", "")
        assert "ApiClient" in js_resp.text


@pytest.mark.asyncio
async def test_api_routes_and_health_precedence_maintained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """API endpoints (/healthz, /api/v1/*, /docs) take precedence over static file router."""
    monkeypatch.setenv("SERVE_FRONTEND", "true")
    from app.config.settings import get_settings

    get_settings.cache_clear()

    service = ResearchService(router=create_default_worker_router(), max_concurrency=2)
    app = create_app(service=service)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Public health check
        health = await client.get("/healthz")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        # REST submission
        create = await client.post(
            "/api/v1/runs",
            json={"query": "Quantum topological insulator inquiry"},
        )
        assert create.status_code == 201
        data = create.json()
        assert data["run_id"].startswith("run_")

        # Security headers present
        assert health.headers.get("x-content-type-options") == "nosniff"
        assert health.headers.get("x-frame-options") == "DENY"


@pytest.mark.asyncio
async def test_frontend_serving_disabled_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """When SERVE_FRONTEND=false, root / returns 404 while API endpoints remain active."""
    monkeypatch.setenv("SERVE_FRONTEND", "false")
    from app.config.settings import get_settings

    get_settings.cache_clear()

    service = ResearchService(router=create_default_worker_router(), max_concurrency=2)
    app = create_app(service=service)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        root = await client.get("/")
        assert root.status_code == 404

        # Health endpoint remains functional
        health = await client.get("/healthz")
        assert health.status_code == 200
