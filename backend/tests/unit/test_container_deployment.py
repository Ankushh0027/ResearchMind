"""Unit tests verifying container deployment entrypoints, healthchecks, and worker runner."""

import asyncio
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.app import create_app
from app.config import AppSettings
from app.jobs.main import StandaloneWorkerRunner
from app.jobs.protocols import JobConsumerProtocol


@pytest.mark.asyncio
async def test_api_production_factory_healthz() -> None:
    """Test 1: Verify create_app factory produces working /healthz response."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "timestamp" in data


@pytest.mark.asyncio
async def test_api_production_openapi_schema() -> None:
    """Test 2: Verify OpenAPI schema generates cleanly and includes core endpoints."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/openapi.json")
        assert response.status_code == 200
        schema: dict[str, Any] = response.json()
        assert "paths" in schema
        assert "/healthz" in schema["paths"]
        assert "/api/v1/runs" in schema["paths"]
        assert "/api/v1/runs/{run_id}" in schema["paths"]
        assert "/api/v1/runs/{run_id}/cancel" in schema["paths"]
        assert "/api/v1/runs/{run_id}/events" in schema["paths"]


def test_deployment_settings_environment_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test 3: Verify worker concurrency and deployment settings read from environment."""
    monkeypatch.setenv("WORKER_CONCURRENCY", "8")
    monkeypatch.setenv("MAX_ORCHESTRATION_CONCURRENCY", "12")
    monkeypatch.setenv("GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS", "45")

    settings = AppSettings()
    assert settings.worker_concurrency == 8
    assert settings.max_orchestration_concurrency == 12
    assert settings.graceful_shutdown_timeout_seconds == 45


@pytest.mark.asyncio
async def test_standalone_worker_runner_lifecycle() -> None:
    """Test 4: Verify StandaloneWorkerRunner starts and shuts down cleanly on stop signal."""

    class DummyConsumer(JobConsumerProtocol):
        def __init__(self) -> None:
            self._running = False

        async def start(self) -> None:
            self._running = True

        async def stop(self) -> None:
            self._running = False

        def is_running(self) -> bool:
            return self._running

    dummy_consumer = DummyConsumer()
    runner = StandaloneWorkerRunner(consumer=dummy_consumer, shutdown_timeout=2.0)

    # Run runner in background task
    runner_task = asyncio.create_task(runner.run())
    await asyncio.sleep(0.05)
    assert dummy_consumer.is_running() is True

    # Signal stop
    runner.signal_stop()
    await asyncio.wait_for(runner_task, timeout=2.0)
    assert dummy_consumer.is_running() is False
