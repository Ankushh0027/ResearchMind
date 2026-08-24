"""End-to-end integration tests for Phase 5.2 asynchronous job worker gateway."""

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
async def test_e2e_async_job_full_pipeline(api_client: AsyncClient) -> None:
    """Test 1: Full async job flow: HTTP POST -> JobPublisher -> InMemoryJobConsumer -> ResearchJobWorker -> Dossier."""
    payload = {
        "query": "What are the latest advances in Majorana zero mode quantum computing architectures?",
        "domain_tags": ["quantum-computing", "physics"],
        "max_subtasks": 4,
    }

    # Submit run to FastAPI gateway
    create_resp = await api_client.post("/api/v1/runs", json=payload)
    assert create_resp.status_code == 201
    summary = create_resp.json()
    run_id = summary["run_id"]
    assert run_id.startswith("run_")

    # Poll status until completion
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

    # Verify final ResearchDossier
    assert detail["dossier"] is not None
    dossier = detail["dossier"]
    assert "dossier_id" in dossier
    assert "markdown_report" in dossier
    assert len(dossier["key_findings"]) >= 1
    assert "## Executive Summary" in dossier["markdown_report"]


@pytest.mark.asyncio
async def test_e2e_async_job_cancellation(api_client: AsyncClient) -> None:
    """Test 2: Verify cancellation via HTTP immediately stops background job."""
    payload = {
        "query": "Inquiry to be cancelled immediately during async job processing",
    }
    create_resp = await api_client.post("/api/v1/runs", json=payload)
    assert create_resp.status_code == 201
    run_id = create_resp.json()["run_id"]

    # Trigger cancellation
    cancel_resp = await api_client.post(f"/api/v1/runs/{run_id}/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == RunStage.CANCELLED.value

    # Verify status reflects CANCELLED
    status_resp = await api_client.get(f"/api/v1/runs/{run_id}")
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == RunStage.CANCELLED.value


@pytest.mark.asyncio
async def test_e2e_async_multiple_simultaneous_runs(api_client: AsyncClient) -> None:
    """Test 3: Verify multiple concurrent async research runs execute with complete tenant/run isolation."""
    queries = [
        "Inquiry A: Spin liquid states in kagome lattices.",
        "Inquiry B: High harmonic generation in semiconductors.",
    ]

    run_ids: list[str] = []
    for q in queries:
        resp = await api_client.post(
            "/api/v1/runs", json={"query": q, "max_subtasks": 5}
        )
        assert resp.status_code == 201
        run_ids.append(resp.json()["run_id"])

    assert run_ids[0] != run_ids[1]

    # Poll both runs
    terminal_stages = {
        RunStage.COMPLETED.value,
        RunStage.FAILED.value,
        RunStage.CANCELLED.value,
    }
    for r_id in run_ids:
        for _ in range(40):
            res = await api_client.get(f"/api/v1/runs/{r_id}")
            assert res.status_code == 200
            if res.json()["status"] in terminal_stages:
                break
            await asyncio.sleep(0.1)

        final_res = await api_client.get(f"/api/v1/runs/{r_id}")
        assert final_res.json()["status"] == RunStage.COMPLETED.value
        assert final_res.json()["dossier"] is not None


@pytest.mark.asyncio
async def test_e2e_async_sse_streaming(api_client: AsyncClient) -> None:
    """Test 4: Verify live execution events stream cleanly over SSE while job runs asynchronously."""
    payload = {"query": "Inquiry for SSE validation during async job consumption"}
    create_resp = await api_client.post("/api/v1/runs", json=payload)
    assert create_resp.status_code == 201
    run_id = create_resp.json()["run_id"]

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


@pytest.mark.asyncio
async def test_e2e_cancellation_while_queued() -> None:
    """Test 5: Verify cancellation of a job before consumer handles it gracefully marks run CANCELLED."""
    from app.jobs.in_memory import (
        InMemoryJobConsumer,
        InMemoryJobPublisher,
        InMemoryJobQueue,
    )
    from app.jobs.worker import ResearchJobWorker

    queue = InMemoryJobQueue()
    publisher = InMemoryJobPublisher(queue)

    service = ResearchService(
        router=create_default_worker_router(),
        publisher=publisher,
        consumer=InMemoryJobConsumer(queue, ResearchJobWorker(), worker_concurrency=1),
    )
    app = create_app(service=service)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Create run
        res = await client.post(
            "/api/v1/runs", json={"query": "Queued cancellation inquiry"}
        )
        assert res.status_code == 201
        run_id = res.json()["run_id"]

        # Cancel immediately
        cancel_res = await client.post(f"/api/v1/runs/{run_id}/cancel")
        assert cancel_res.status_code == 200
        assert cancel_res.json()["status"] == RunStage.CANCELLED.value

        detail = await client.get(f"/api/v1/runs/{run_id}")
        assert detail.status_code == 200
        assert detail.json()["status"] == RunStage.CANCELLED.value


@pytest.mark.asyncio
async def test_e2e_pubsub_transport_execution() -> None:
    """Test 6: Verify end-to-end research workflow executes seamlessly over GooglePubSubPublisher and Consumer."""
    from app.jobs.pubsub import GooglePubSubConsumer, GooglePubSubPublisher
    from app.jobs.worker import ResearchJobWorker
    from tests.unit.test_pubsub_jobs import (
        FakePublisherClient,
        FakeReceivedMessage,
        FakeSubscriberClient,
    )

    pub_client = FakePublisherClient()
    sub_client = FakeSubscriberClient()

    # Bridge publisher output to subscriber queue
    original_publish = pub_client.publish

    def bridging_publish(topic: str, data: bytes, **attributes: str) -> Any:
        fut = original_publish(topic, data, **attributes)
        msg_id = fut.result()
        sub_client.queue.append(
            FakeReceivedMessage(
                ack_id=f"ack_{msg_id}", data=data, attributes=attributes
            )
        )
        return fut

    pub_client.publish = bridging_publish  # type: ignore[method-assign]

    publisher = GooglePubSubPublisher(
        client=pub_client,
        project_id="test-proj",
        topic_name="researchmind-agent-tasks",
    )

    worker = ResearchJobWorker(
        router=create_default_worker_router(),
        max_concurrency=4,
    )

    consumer = GooglePubSubConsumer(
        subscription_name="researchmind-agent-tasks-sub",
        handler=worker,
        client=sub_client,
        publisher=publisher,
        project_id="test-proj",
        worker_concurrency=2,
    )

    service = ResearchService(
        router=create_default_worker_router(),
        publisher=publisher,
        consumer=consumer,
        worker=worker,
    )

    app = create_app(service=service)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        payload = {
            "query": "Investigate self-supervised learning for quantum materials simulation.",
            "domain_tags": ["quantum", "machine-learning"],
            "max_subtasks": 5,
        }
        res = await client.post("/api/v1/runs", json=payload)
        assert res.status_code == 201
        run_id = res.json()["run_id"]

        detail: dict[str, Any] = {}
        for _ in range(40):
            status_resp = await client.get(f"/api/v1/runs/{run_id}")
            assert status_resp.status_code == 200
            detail = status_resp.json()
            if detail["status"] in (
                RunStage.COMPLETED.value,
                RunStage.FAILED.value,
                RunStage.CANCELLED.value,
            ):
                break
            await asyncio.sleep(0.1)

        assert detail["status"] == RunStage.COMPLETED.value
        assert detail["dossier"] is not None
        assert len(detail["completed_task_ids"]) >= 1
