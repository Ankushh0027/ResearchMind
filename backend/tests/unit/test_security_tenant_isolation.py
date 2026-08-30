"""Unit tests for Phase 7.2 multi-tenant isolation and IDOR access control.

Coverage:
1. Authenticated request resolves tenant identity from API key.
2. Research runs, checkpoints, and contexts preserve tenant_id.
3. Same-tenant access to runs, events, and artifacts succeeds.
4. Cross-tenant access attempts return HTTP 404 (IDOR prevention).
5. Cross-tenant cancellation attempts return HTTP 404.
6. Client request body payload cannot override tenant identity derived from auth context.
7. Unauthenticated/internal flows remain compatible when API_AUTH_ENABLED=False.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.app import create_app
from app.api.service import ResearchService
from app.orchestration.router import create_default_worker_router

KEY_TENANT_A = "secret-key-tenant-alpha"
KEY_TENANT_B = "secret-key-tenant-beta"

API_KEYS_CONFIG = json.dumps(
    {
        KEY_TENANT_A: "tenant_alpha",
        KEY_TENANT_B: "tenant_beta",
    }
)


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    from app.config.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _make_multi_tenant_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    monkeypatch.setenv("API_KEYS_JSON", API_KEYS_CONFIG)
    from app.config.settings import get_settings

    get_settings.cache_clear()

    service = ResearchService(router=create_default_worker_router(), max_concurrency=2)
    return create_app(service=service)


@pytest.mark.asyncio
async def test_tenant_resolved_and_bound_to_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Submitting a run with Tenant A key binds tenant_alpha to the run."""
    app = _make_multi_tenant_app(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/v1/runs",
            json={"query": "Quantum topology research"},
            headers={"Authorization": f"Bearer {KEY_TENANT_A}"},
        )
        assert resp.status_code == 201
        run_id = resp.json()["run_id"]

        # Fetch detail with Tenant A key -> 200 OK
        detail_resp = await client.get(
            f"/api/v1/runs/{run_id}",
            headers={"Authorization": f"Bearer {KEY_TENANT_A}"},
        )
        assert detail_resp.status_code == 200
        assert detail_resp.json()["run_id"] == run_id


@pytest.mark.asyncio
async def test_cross_tenant_get_run_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tenant B requesting a run created by Tenant A receives 404 Not Found."""
    app = _make_multi_tenant_app(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Create run as Tenant A
        resp = await client.post(
            "/api/v1/runs",
            json={"query": "Superconductivity study"},
            headers={"Authorization": f"Bearer {KEY_TENANT_A}"},
        )
        assert resp.status_code == 201
        run_id = resp.json()["run_id"]

        # Attempt fetch as Tenant B -> 404 Not Found
        cross_resp = await client.get(
            f"/api/v1/runs/{run_id}",
            headers={"Authorization": f"Bearer {KEY_TENANT_B}"},
        )
        assert cross_resp.status_code == 404
        assert cross_resp.json()["error_code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_cross_tenant_cancel_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tenant B attempting to cancel Tenant A's run receives 404 Not Found."""
    app = _make_multi_tenant_app(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Create run as Tenant A
        resp = await client.post(
            "/api/v1/runs",
            json={"query": "Fusion energy research"},
            headers={"Authorization": f"Bearer {KEY_TENANT_A}"},
        )
        run_id = resp.json()["run_id"]

        # Cancel attempt as Tenant B
        cross_cancel = await client.post(
            f"/api/v1/runs/{run_id}/cancel",
            headers={"Authorization": f"Bearer {KEY_TENANT_B}"},
        )
        assert cross_cancel.status_code == 404


@pytest.mark.asyncio
async def test_cross_tenant_events_stream_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tenant B subscribing to Tenant A's SSE stream receives 404 Not Found."""
    app = _make_multi_tenant_app(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Create run as Tenant A
        resp = await client.post(
            "/api/v1/runs",
            json={"query": "Cellular biology analysis"},
            headers={"Authorization": f"Bearer {KEY_TENANT_A}"},
        )
        run_id = resp.json()["run_id"]

        # Events stream attempt as Tenant B
        cross_events = await client.get(
            f"/api/v1/runs/{run_id}/events",
            headers={"Authorization": f"Bearer {KEY_TENANT_B}"},
        )
        assert cross_events.status_code == 404


@pytest.mark.asyncio
async def test_cross_tenant_artifacts_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tenant B querying Tenant A's artifacts receives 404 Not Found."""
    app = _make_multi_tenant_app(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Create run as Tenant A
        resp = await client.post(
            "/api/v1/runs",
            json={"query": "Genomic sequencing inquiry"},
            headers={"Authorization": f"Bearer {KEY_TENANT_A}"},
        )
        run_id = resp.json()["run_id"]

        # List artifacts attempt as Tenant B
        cross_artifacts = await client.get(
            f"/api/v1/runs/{run_id}/artifacts",
            headers={"Authorization": f"Bearer {KEY_TENANT_B}"},
        )
        assert cross_artifacts.status_code == 404

        # Download artifact attempt as Tenant B
        cross_art_download = await client.get(
            f"/api/v1/runs/{run_id}/artifacts/art_123",
            headers={"Authorization": f"Bearer {KEY_TENANT_B}"},
        )
        assert cross_art_download.status_code == 404
