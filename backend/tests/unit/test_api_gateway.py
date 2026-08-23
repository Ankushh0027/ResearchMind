"""Unit tests for Phase 5.1 FastAPI REST gateway endpoints and schemas."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.app import create_app
from app.api.service import ResearchService
from app.common.enums import RunStage
from app.orchestration.router import create_default_worker_router


@pytest.fixture
def api_client() -> AsyncClient:
    service = ResearchService(router=create_default_worker_router())
    app = create_app(service=service)
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://testserver")


@pytest.mark.asyncio
async def test_health_check_endpoint(api_client: AsyncClient) -> None:
    """Test 1: Verify /healthz returns status ok and API version."""
    response = await api_client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_create_research_run_validation_success(api_client: AsyncClient) -> None:
    """Test 2: Verify POST /api/v1/runs creates a run and returns 201 Created."""
    payload = {
        "query": "Investigate mechanisms of electronic nematicity in iron-based superconductors.",
        "domain_tags": ["physics", "superconductivity"],
        "max_subtasks": 5,
    }
    response = await api_client.post("/api/v1/runs", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["run_id"].startswith("run_")
    assert data["goal_query"] == payload["query"]
    assert data["status"] in [s.value for s in RunStage]


@pytest.mark.asyncio
async def test_create_research_run_validation_failure(api_client: AsyncClient) -> None:
    """Test 3: Verify POST /api/v1/runs rejects empty/short queries with 422."""
    payload = {
        "query": "a",  # min_length=3
    }
    response = await api_client.post("/api/v1/runs", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_research_run_not_found(api_client: AsyncClient) -> None:
    """Test 4: Verify GET /api/v1/runs/{run_id} returns 404 for unknown run."""
    response = await api_client.get("/api/v1/runs/run_unknown_999")
    assert response.status_code == 404
    data = response.json()
    assert "not found" in data["detail"].lower()


@pytest.mark.asyncio
async def test_cancel_research_run_not_found(api_client: AsyncClient) -> None:
    """Test 5: Verify POST /api/v1/runs/{run_id}/cancel returns 404 for unknown run."""
    response = await api_client.post("/api/v1/runs/run_unknown_999/cancel")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_openapi_schema_generation(api_client: AsyncClient) -> None:
    """Test 6: Verify OpenAPI documentation schema is generated successfully."""
    response = await api_client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "ResearchMind API"
    assert "/api/v1/runs" in schema["paths"]
    assert "/healthz" in schema["paths"]
