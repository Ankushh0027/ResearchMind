"""Integration tests for Phase 5.1 FastAPI HTTP client lifecycle."""

import asyncio
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.app import create_app
from app.api.service import ResearchService
from app.common.enums import RunStage
from app.orchestration.router import create_default_worker_router


@pytest.fixture
def api_client() -> AsyncClient:
    service = ResearchService(router=create_default_worker_router(), max_concurrency=4)
    app = create_app(service=service)
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://testserver")


@pytest.mark.asyncio
async def test_e2e_api_run_submission_and_dossier_retrieval(
    api_client: AsyncClient,
) -> None:
    """Test 1 Integration: Submit research inquiry, poll until completion, and retrieve publication-grade ResearchDossier."""
    payload = {
        "query": "What are the mechanisms of d-wave pairing in high-temperature cuprate superconductors?",
        "domain_tags": ["condensed-matter", "superconductivity"],
        "max_subtasks": 4,
    }

    # Step 1: Submit research run
    create_resp = await api_client.post("/api/v1/runs", json=payload)
    assert create_resp.status_code == 201
    summary = create_resp.json()
    run_id = summary["run_id"]
    assert run_id.startswith("run_")

    # Step 2: Poll status until completion
    terminal_stages = {
        RunStage.COMPLETED.value,
        RunStage.FAILED.value,
        RunStage.CANCELLED.value,
    }
    detail: dict[str, Any] = {}
    for _ in range(40):
        status_resp = await api_client.get(f"/api/v1/runs/{run_id}")
        assert status_resp.status_code == 200
        detail = status_resp.json()
        if detail["status"] in terminal_stages:
            break
        await asyncio.sleep(0.1)

    assert detail["status"] == RunStage.COMPLETED.value
    assert len(detail["completed_task_ids"]) >= 1

    # Step 3: Inspect final ResearchDossier
    assert detail["dossier"] is not None
    dossier = detail["dossier"]
    assert "dossier_id" in dossier
    assert "markdown_report" in dossier
    assert len(dossier["key_findings"]) >= 1
    assert len(dossier["citations"]) >= 1
    assert "## Executive Summary" in dossier["markdown_report"]


@pytest.mark.asyncio
async def test_e2e_api_cancellation_flow(api_client: AsyncClient) -> None:
    """Test 2 Integration: Submit research inquiry and cancel immediately."""
    payload = {
        "query": "Inquiry to be cancelled promptly by client",
    }
    create_resp = await api_client.post("/api/v1/runs", json=payload)
    assert create_resp.status_code == 201
    run_id = create_resp.json()["run_id"]

    # Cancel the run
    cancel_resp = await api_client.post(f"/api/v1/runs/{run_id}/cancel")
    assert cancel_resp.status_code == 200
    cancel_data = cancel_resp.json()
    assert cancel_data["status"] == RunStage.CANCELLED.value

    # Verify status is recorded as CANCELLED
    status_resp = await api_client.get(f"/api/v1/runs/{run_id}")
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == RunStage.CANCELLED.value


@pytest.mark.asyncio
async def test_e2e_api_event_streaming_sse(api_client: AsyncClient) -> None:
    """Test 3 Integration: Verify Server-Sent Events (SSE) stream endpoint returns live events."""
    payload = {
        "query": "Inquiry for SSE streaming validation",
    }
    create_resp = await api_client.post("/api/v1/runs", json=payload)
    assert create_resp.status_code == 201
    run_id = create_resp.json()["run_id"]

    # Stream events
    events_received: list[str] = []
    async with api_client.stream("GET", f"/api/v1/runs/{run_id}/events") as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        async for line in response.aiter_lines():
            if line.startswith("event:") or line.startswith("data:"):
                events_received.append(line)
            if len(events_received) >= 4:
                break

    assert len(events_received) >= 2
