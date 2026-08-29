"""End-to-end integration tests for Phase 6.7: Distributed Tracing, Metrics, and Observability."""

import asyncio
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.app import create_app
from app.api.service import ResearchService
from app.config.settings import AppSettings
from app.observability import (
    DefaultTelemetryProvider,
    InMemoryMetricsAccumulator,
    InMemoryTracer,
    get_metrics,
    get_tracer,
    set_global_telemetry_provider,
)
from app.orchestration.runtime import (
    InMemoryCheckpointRepository,
)
from app.persistence.in_memory import InMemoryRunRepository
from app.storage.factory import create_artifact_storage


@pytest.fixture(autouse=True)
def _reset_telemetry() -> Any:
    """Reset global telemetry provider before and after each test."""
    tracer = InMemoryTracer()
    metrics = InMemoryMetricsAccumulator()
    provider = DefaultTelemetryProvider(tracer=tracer, metrics=metrics)
    set_global_telemetry_provider(provider)
    yield
    set_global_telemetry_provider(None)


@pytest.mark.asyncio
async def test_e2e_distributed_trace_propagation() -> None:
    """Verify end-to-end trace correlation:

    HTTP POST /api/v1/runs -> TraceContextMiddleware
      -> Service create_and_start_run
      -> JobEnvelope.traceparent
      -> Worker handle_job
      -> DAG execution child spans
      -> Artifact storage
      -> HTTP response headers match.
    """
    settings = AppSettings(
        APP_ENV="test",
        API_AUTH_ENABLED=False,
        API_KEY="test_api_key",
        ARTIFACT_STORAGE_PROVIDER="in_memory",
    )

    run_repo = InMemoryRunRepository()
    checkpoint_repo = InMemoryCheckpointRepository()
    artifact_storage = create_artifact_storage(settings=settings)

    service = ResearchService(
        run_repo=run_repo,
        checkpoint_repo=checkpoint_repo,
        artifact_storage=artifact_storage,
    )

    app = create_app(service=service)

    custom_trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
    custom_span_id = "00f067aa0ba902b7"
    incoming_traceparent = f"00-{custom_trace_id}-{custom_span_id}-01"

    await service.start()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Submit research run with W3C traceparent header
            response = await client.post(
                "/api/v1/runs",
                json={
                    "query": "Quantum computing error mitigation in superconducting qubits",
                    "max_subtasks": 5,
                },
                headers={
                    "X-API-Key": "test_api_key",
                    "traceparent": incoming_traceparent,
                },
            )

            assert response.status_code == 201
            data = response.json()
            run_id = data["run_id"]

            # Verify HTTP response contains correlated trace ID and traceparent header
            assert response.headers.get("X-Trace-ID") == custom_trace_id
            assert custom_trace_id in (response.headers.get("traceparent") or "")

            # Wait for the background worker to execute DAG and upload artifacts
            for _ in range(60):
                detail_res = await client.get(
                    f"/api/v1/runs/{run_id}",
                    headers={"X-API-Key": "test_api_key"},
                )
                if detail_res.status_code == 200:
                    run_detail = detail_res.json()
                    if run_detail["status"] in ("COMPLETED", "FAILED"):
                        break
                await asyncio.sleep(0.05)

            assert run_detail["status"] == "COMPLETED"

            # Verify artifacts were created
            artifacts_res = await client.get(
                f"/api/v1/runs/{run_id}/artifacts",
                headers={"X-API-Key": "test_api_key"},
            )
            assert artifacts_res.status_code == 200
            artifacts_list = artifacts_res.json()
            assert len(artifacts_list) >= 2
    finally:
        await service.stop()

    # Verify telemetry traces recorded in InMemoryTracer
    tracer = get_tracer()
    assert isinstance(tracer, InMemoryTracer)
    spans = tracer.get_spans()
    assert len(spans) > 0

    # Ensure at least one span shares the trace_id from the incoming request
    matching_spans = [s for s in spans if s.context.trace_id == custom_trace_id]
    assert len(matching_spans) > 0

    # Verify metrics recorded in InMemoryMetricsAccumulator
    metrics = get_metrics()
    summary = metrics.get_summary()
    assert summary.total_runs_started >= 1
    assert summary.total_runs_completed >= 1
    assert summary.total_tasks_completed >= 1


@pytest.mark.asyncio
async def test_e2e_trace_generation_when_no_header_provided() -> None:
    """Verify that when no traceparent header is provided, a fresh trace is generated and propagated."""
    settings = AppSettings(
        APP_ENV="test",
        API_AUTH_ENABLED=False,
        API_KEY="test_api_key",
        ARTIFACT_STORAGE_PROVIDER="in_memory",
    )

    run_repo = InMemoryRunRepository()
    service = ResearchService(
        run_repo=run_repo,
        artifact_storage=create_artifact_storage(settings=settings),
    )
    app = create_app(service=service)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/healthz")
        assert response.status_code == 200
        trace_id = response.headers.get("X-Trace-ID")
        traceparent = response.headers.get("traceparent")

        assert trace_id is not None
        assert len(trace_id) == 32
        assert traceparent is not None
        assert traceparent.startswith(f"00-{trace_id}-")
