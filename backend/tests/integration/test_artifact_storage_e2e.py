"""Integration test verifying end-to-end artifact lifecycle across worker, storage, repository, and API."""

from __future__ import annotations

import hashlib

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.app import create_app
from app.api.service import ResearchService
from app.common.enums import RunStage
from app.jobs.protocols import JobEnvelope, JobStatus
from app.jobs.worker import ResearchJobWorker
from app.orchestration.router import create_default_worker_router
from app.persistence.in_memory import (
    InMemoryCheckpointRepository,
    InMemoryRunRepository,
)
from app.persistence.protocols import RunRecord
from app.state.models import ResearchGoal
from app.storage.in_memory import InMemoryArtifactStorage
from app.storage.models import ArtifactType


@pytest.mark.asyncio
async def test_worker_generates_and_persists_artifacts_to_run_record() -> None:
    """Test 1: Worker uploads report.md and dossier.json upon DAG completion and syncs metadata to RunRecord."""
    run_repo = InMemoryRunRepository()
    checkpoint_repo = InMemoryCheckpointRepository()
    artifact_storage = InMemoryArtifactStorage()

    run_id = "run_art_e2e_01"
    goal = ResearchGoal(goal_id="goal_01", query="Quantum error correction thresholds")

    initial_record = RunRecord(
        run_id=run_id,
        goal=goal,
        status=RunStage.QUEUED,
    )
    await run_repo.create_run(initial_record)

    worker = ResearchJobWorker(
        router=create_default_worker_router(),
        run_repo=run_repo,
        checkpoint_repo=checkpoint_repo,
        artifact_storage=artifact_storage,
        max_concurrency=2,
    )

    envelope = JobEnvelope(
        job_id="job_01",
        run_id=run_id,
        goal_query=goal.query,
    )

    result_env = await worker.handle_job(envelope)
    assert result_env.status == JobStatus.COMPLETED

    # Verify RunRecord in repository has persisted artifact references
    updated_record = await run_repo.get_run(run_id)
    assert updated_record is not None
    assert updated_record.status == RunStage.COMPLETED
    assert len(updated_record.artifacts) >= 2

    # Find the report markdown artifact
    report_art = next(
        (
            a
            for a in updated_record.artifacts
            if a.artifact_type == ArtifactType.REPORT_MARKDOWN
        ),
        None,
    )
    assert report_art is not None
    assert report_art.object_key == f"{run_id}/report.md"
    assert report_art.content_type == "text/markdown"
    assert report_art.size_bytes > 0

    # Find the dossier JSON artifact
    dossier_art = next(
        (
            a
            for a in updated_record.artifacts
            if a.artifact_type == ArtifactType.DOSSIER_JSON
        ),
        None,
    )
    assert dossier_art is not None
    assert dossier_art.object_key == f"{run_id}/dossier.json"
    assert dossier_art.content_type == "application/json"
    assert dossier_art.size_bytes > 0

    # Verify downloading and checksum integrity
    report_bytes = await artifact_storage.download(report_art, verify_checksum=True)
    assert hashlib.sha256(report_bytes).hexdigest() == report_art.sha256
    assert len(report_bytes) == report_art.size_bytes


@pytest.mark.asyncio
async def test_cross_service_instance_artifact_recovery() -> None:
    """Test 2: A new service instance B can load a run from repo and resolve/download its durable artifacts."""
    shared_run_repo = InMemoryRunRepository()
    shared_artifact_storage = InMemoryArtifactStorage()

    run_id = "run_art_e2e_02"
    goal = ResearchGoal(goal_id="goal_02", query="CRISPR off-target editing mitigation")

    # Upload an artifact directly to storage
    content = "# Publication Report\n\nHigh precision Cas9 variants."
    artifact_meta = await shared_artifact_storage.upload(
        run_id=run_id,
        artifact_type=ArtifactType.REPORT_MARKDOWN,
        content=content,
        filename="report.md",
    )

    # Persist RunRecord with this artifact reference
    record = RunRecord(
        run_id=run_id,
        goal=goal,
        status=RunStage.COMPLETED,
        artifacts=(artifact_meta,),
    )
    await shared_run_repo.create_run(record)

    # New Service Instance B initialized with the shared repo and storage
    service_b = ResearchService(
        router=create_default_worker_router(),
        run_repo=shared_run_repo,
        artifact_storage=shared_artifact_storage,
        max_concurrency=2,
    )

    # Fetch run detail
    detail = await service_b.get_run(run_id)
    assert detail is not None
    assert len(detail.artifacts) == 1
    assert detail.artifacts[0].artifact_id == artifact_meta.artifact_id

    # Retrieve artifact through service B
    retrieved = await service_b.get_artifact(run_id, artifact_meta.artifact_id)
    assert retrieved is not None
    meta_out, content_out = retrieved
    assert meta_out.sha256 == artifact_meta.sha256
    assert content_out.decode("utf-8") == content


@pytest.mark.asyncio
async def test_rest_api_artifact_endpoints_and_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test 3: REST API /api/v1/runs/{run_id}/artifacts endpoints serve metadata and content under auth."""
    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    monkeypatch.setenv("API_KEY", "secret-test-key-66")
    from app.config.settings import get_settings

    get_settings.cache_clear()

    run_repo = InMemoryRunRepository()
    artifact_storage = InMemoryArtifactStorage()

    run_id = "run_api_art_01"
    goal = ResearchGoal(goal_id="g1", query="Neural network pruning")

    raw_markdown = "# Pruned Transformer Analysis"
    art_meta = await artifact_storage.upload(
        run_id=run_id,
        artifact_type=ArtifactType.REPORT_MARKDOWN,
        content=raw_markdown,
        filename="report.md",
    )

    record = RunRecord(
        run_id=run_id,
        goal=goal,
        status=RunStage.COMPLETED,
        artifacts=(art_meta,),
    )
    await run_repo.create_run(record)

    service = ResearchService(
        router=create_default_worker_router(),
        run_repo=run_repo,
        artifact_storage=artifact_storage,
        max_concurrency=2,
    )
    app = create_app(service=service)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Unauthenticated request -> 401
        resp_unauth = await client.get(f"/api/v1/runs/{run_id}/artifacts")
        assert resp_unauth.status_code == 401

        # 2. Authenticated list artifacts -> 200
        headers = {"Authorization": "Bearer secret-test-key-66"}
        resp_list = await client.get(
            f"/api/v1/runs/{run_id}/artifacts", headers=headers
        )
        assert resp_list.status_code == 200
        artifacts_list = resp_list.json()
        assert len(artifacts_list) == 1
        assert artifacts_list[0]["artifact_id"] == art_meta.artifact_id
        assert artifacts_list[0]["artifact_type"] == "report_markdown"

        # 3. Authenticated download content -> 200 with ETag and matching content
        resp_get = await client.get(
            f"/api/v1/runs/{run_id}/artifacts/{art_meta.artifact_id}",
            headers=headers,
        )
        assert resp_get.status_code == 200
        assert resp_get.text == raw_markdown
        assert resp_get.headers.get("etag") == f'"{art_meta.sha256}"'
        assert "text/markdown" in resp_get.headers.get("content-type", "")

        # 4. Authenticated metadata endpoint -> 200
        resp_meta = await client.get(
            f"/api/v1/runs/{run_id}/artifacts/{art_meta.artifact_id}/metadata",
            headers=headers,
        )
        assert resp_meta.status_code == 200
        meta_data = resp_meta.json()
        assert meta_data["sha256"] == art_meta.sha256
        assert meta_data["size_bytes"] == len(raw_markdown.encode("utf-8"))

        # 5. Non-existent artifact -> 404
        resp_404 = await client.get(
            f"/api/v1/runs/{run_id}/artifacts/art_nonexistent_999",
            headers=headers,
        )
        assert resp_404.status_code == 404
