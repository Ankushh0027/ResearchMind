"""Comprehensive Browser-Level E2E and Failure Recovery Test Suite (Phase 7.4)."""

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
async def test_e2e_critical_journey_simulation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate full end-to-end user workflow:
    Open App -> Probe Health -> Submit Inquiry -> Stream SSE -> Retrieve Run & Artifacts.
    """
    monkeypatch.setenv("SERVE_FRONTEND", "true")
    monkeypatch.setenv("API_AUTH_ENABLED", "false")
    from app.config.settings import get_settings

    get_settings.cache_clear()

    service = ResearchService(router=create_default_worker_router(), max_concurrency=2)
    app = create_app(service=service)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Open Application Shell
        root_resp = await client.get("/")
        assert root_resp.status_code == 200
        assert "ResearchMind" in root_resp.text
        assert 'role="main"' in root_resp.text

        # 2. Check Health
        health_resp = await client.get("/healthz")
        assert health_resp.status_code == 200
        assert health_resp.json()["status"] == "ok"

        # 3. Submit Research Inquiry
        submit_resp = await client.post(
            "/api/v1/runs",
            json={
                "query": "Quantum topological insulator phase transitions",
                "domain_tags": ["physics", "quantum"],
                "max_subtasks": 5,
            },
        )
        assert submit_resp.status_code == 201
        run_data = submit_resp.json()
        run_id = run_data["run_id"]
        assert run_id.startswith("run_")

        # 4. Stream SSE Events
        sse_resp = await client.get(f"/api/v1/runs/{run_id}/events")
        assert sse_resp.status_code == 200
        assert "text/event-stream" in sse_resp.headers.get("content-type", "")

        # 5. Retrieve Run Details
        detail_resp = await client.get(f"/api/v1/runs/{run_id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["run_id"] == run_id

        # 6. List Artifacts
        art_resp = await client.get(f"/api/v1/runs/{run_id}/artifacts")
        assert art_resp.status_code == 200
        assert isinstance(art_resp.json(), list)


@pytest.mark.asyncio
async def test_auth_failure_and_recovery_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate 401 unauthorized rejection when API auth is enabled and recovery with valid key."""
    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    monkeypatch.setenv("API_KEY", "secret-test-token-12345")
    from app.config.settings import get_settings

    get_settings.cache_clear()

    service = ResearchService(router=create_default_worker_router(), max_concurrency=2)
    app = create_app(service=service)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Public health remains accessible without auth
        health = await client.get("/healthz")
        assert health.status_code == 200

        # Unauthenticated run creation rejected with 401
        unauth_resp = await client.post(
            "/api/v1/runs",
            json={"query": "Test unauthenticated inquiry"},
        )
        assert unauth_resp.status_code == 401
        assert "Bearer" in unauth_resp.headers.get("www-authenticate", "")

        # Authenticated run creation succeeds
        auth_resp = await client.post(
            "/api/v1/runs",
            json={"query": "Test authenticated inquiry"},
            headers={"Authorization": "Bearer secret-test-token-12345"},
        )
        assert auth_resp.status_code == 201


@pytest.mark.asyncio
async def test_validation_failure_handling(monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate 422 for invalid payloads (e.g. empty or too short query)."""
    monkeypatch.setenv("API_AUTH_ENABLED", "false")
    from app.config.settings import get_settings

    get_settings.cache_clear()

    service = ResearchService(router=create_default_worker_router(), max_concurrency=2)
    app = create_app(service=service)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Query too short (< 3 chars)
        short_resp = await client.post(
            "/api/v1/runs",
            json={"query": "ab"},
        )
        assert short_resp.status_code == 422
        data = short_resp.json()
        assert data["error_code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_resource_not_found_handling(monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate 404 for nonexistent runs or artifacts."""
    monkeypatch.setenv("API_AUTH_ENABLED", "false")
    from app.config.settings import get_settings

    get_settings.cache_clear()

    service = ResearchService(router=create_default_worker_router(), max_concurrency=2)
    app = create_app(service=service)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/api/v1/runs/run_nonexistent_9999")
        assert resp.status_code == 404

        art_resp = await client.get("/api/v1/runs/run_nonexistent_9999/artifacts")
        assert art_resp.status_code == 404


@pytest.mark.asyncio
async def test_run_cancellation_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate cooperative cancellation endpoint."""
    monkeypatch.setenv("API_AUTH_ENABLED", "false")
    from app.config.settings import get_settings

    get_settings.cache_clear()

    service = ResearchService(router=create_default_worker_router(), max_concurrency=2)
    app = create_app(service=service)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        create = await client.post(
            "/api/v1/runs",
            json={"query": "Cancellation test inquiry"},
        )
        run_id = create.json()["run_id"]

        cancel = await client.post(f"/api/v1/runs/{run_id}/cancel")
        assert cancel.status_code == 200
        data = cancel.json()
        assert data["status"] in ("CANCELLED", "COMPLETED", "FAILED")
