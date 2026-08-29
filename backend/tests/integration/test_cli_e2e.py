"""End-to-end integration tests verifying ResearchMind CLI commands against in-memory FastAPI application."""

import os
import tempfile

import pytest

from app.api.app import create_app
from app.api.routes import set_global_service
from app.api.service import ResearchService
from app.cli.client import CLIClientError, ResearchMindClient
from app.persistence.in_memory import (
    InMemoryCheckpointRepository,
    InMemoryRunRepository,
)
from app.storage.in_memory import InMemoryArtifactStorage
from app.storage.models import ArtifactType


@pytest.fixture
def mock_service() -> ResearchService:
    run_repo = InMemoryRunRepository()
    ckpt_repo = InMemoryCheckpointRepository()
    storage = InMemoryArtifactStorage()
    service = ResearchService(
        run_repo=run_repo,
        checkpoint_repo=ckpt_repo,
        artifact_storage=storage,
    )
    set_global_service(service)
    return service


@pytest.fixture
def cli_client(mock_service: ResearchService) -> ResearchMindClient:
    app = create_app(service=mock_service)
    return ResearchMindClient(
        base_url="http://testserver",
        api_key="test-api-key",
        app=app,
    )


class TestCLIE2E:
    """Integration test suite executing CLI client operations against in-memory API."""

    def test_health_check(self, cli_client: ResearchMindClient) -> None:
        data = cli_client.health()
        assert data.get("status") == "ok"
        assert "version" in data
        assert "timestamp" in data

    def test_submit_and_get_status(self, cli_client: ResearchMindClient) -> None:
        # 1. Submit inquiry
        submit_res = cli_client.submit_run(
            query="Evaluate cross-chain interoperability protocols.",
            domain_tags=["crypto", "systems"],
            max_subtasks=4,
        )
        run_id = submit_res["run_id"]
        assert run_id.startswith("run_")
        assert submit_res["status"] == "QUEUED"

        # 2. Get status
        status_res = cli_client.get_run(run_id)
        assert status_res["run_id"] == run_id
        assert "status" in status_res
        assert "completed_task_ids" in status_res

    def test_cancel_run(self, cli_client: ResearchMindClient) -> None:
        submit_res = cli_client.submit_run(
            query="Long running analysis for cancellation testing.",
        )
        run_id = submit_res["run_id"]

        cancel_res = cli_client.cancel_run(run_id)
        assert cancel_res["run_id"] == run_id
        assert cancel_res["status"] == "CANCELLED"

    def test_get_nonexistent_run_raises_404(
        self, cli_client: ResearchMindClient
    ) -> None:
        with pytest.raises(CLIClientError) as exc_info:
            cli_client.get_run("run_nonexistent_99999")
        assert exc_info.value.status_code == 404
        assert exc_info.value.error_code == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_artifact_listing_and_download(
        self, cli_client: ResearchMindClient, mock_service: ResearchService
    ) -> None:
        # Submit run
        submit_res = cli_client.submit_run(
            query="Test artifact export and download pipeline.",
        )
        run_id = submit_res["run_id"]

        # Store test artifact directly into storage backend
        test_payload = b"# Research Report\n\nSynthesized findings and evidence."
        meta = await mock_service.artifact_storage.upload(
            run_id=run_id,
            artifact_type=ArtifactType.REPORT_MARKDOWN,
            content=test_payload,
            filename="report.md",
            content_type="text/markdown",
        )

        context = mock_service._runs.get(run_id)
        if context is not None:
            context.artifacts.append(meta)

        record = await mock_service.run_repository.get_run(run_id)
        if record is not None:
            await mock_service.run_repository.update_run(
                record.with_updates(artifacts=[meta])
            )

        # 1. List artifacts
        artifacts = cli_client.list_artifacts(run_id)
        assert len(artifacts) >= 1
        artifact_ids = [a["artifact_id"] for a in artifacts]
        assert meta.artifact_id in artifact_ids

        # 2. Download artifact to temporary directory
        with tempfile.TemporaryDirectory() as tmpdir:
            target_file = os.path.join(tmpdir, "downloaded_report.md")
            bytes_written = cli_client.download_artifact(
                run_id, meta.artifact_id, target_file
            )
            assert bytes_written == len(test_payload)
            assert os.path.exists(target_file)
            with open(target_file, "rb") as f:
                assert f.read() == test_payload
