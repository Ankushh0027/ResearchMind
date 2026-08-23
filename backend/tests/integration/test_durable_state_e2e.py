import asyncio

import pytest

from app.api.schemas import CreateRunRequest
from app.api.service import ResearchService
from app.common.enums import RunStage
from app.jobs.in_memory import (
    InMemoryJobConsumer,
    InMemoryJobPublisher,
    InMemoryJobQueue,
)
from app.jobs.worker import ResearchJobWorker
from app.orchestration.router import create_default_worker_router
from app.persistence.in_memory import (
    InMemoryCheckpointRepository,
    InMemoryRunRepository,
)


@pytest.mark.asyncio
async def test_durable_state_cross_service_persistence() -> None:
    """Test 1: Proves that a fresh ResearchService instance retrieves completed run state and dossier from RunRepository."""
    # Shared durable repositories
    shared_run_repo = InMemoryRunRepository()
    shared_checkpoint_repo = InMemoryCheckpointRepository()
    shared_queue = InMemoryJobQueue()

    publisher = InMemoryJobPublisher(shared_queue)
    router = create_default_worker_router()

    worker = ResearchJobWorker(
        router=router,
        run_repo=shared_run_repo,
        checkpoint_repo=shared_checkpoint_repo,
        max_concurrency=2,
    )

    consumer = InMemoryJobConsumer(
        queue=shared_queue, handler=worker, worker_concurrency=1
    )

    # Service Instance A: handles ingestion
    service_a = ResearchService(
        router=router,
        publisher=publisher,
        consumer=consumer,
        worker=worker,
        run_repo=shared_run_repo,
        checkpoint_repo=shared_checkpoint_repo,
    )

    await service_a.start()

    try:
        # Submit run via Service Instance A
        req = CreateRunRequest(
            query="Evaluate state persistence and recovery in distributed multi-agent systems",
            domain_tags=("systems", "ai"),
            max_subtasks=5,
        )
        summary = await service_a.create_and_start_run(req)
        run_id = summary.run_id

        # Poll until worker completes the workflow
        for _ in range(60):
            detail = await service_a.get_run(run_id)
            if detail and detail.status in (RunStage.COMPLETED, RunStage.FAILED):
                break
            await asyncio.sleep(0.05)

        assert detail is not None
        assert detail.status == RunStage.COMPLETED
        assert detail.dossier is not None

        # NOW: Spin up Service Instance B — a brand new instance with EMPTY RAM dictionary
        service_b = ResearchService(
            run_repo=shared_run_repo,
            checkpoint_repo=shared_checkpoint_repo,
        )

        # Service B has empty in-memory runs dictionary
        assert run_id not in service_b._runs

        # Service B queries the run: should seamlessly load durable record from shared_run_repo
        retrieved_run = await service_b.get_run(run_id)
        assert retrieved_run is not None
        assert retrieved_run.run_id == run_id
        assert retrieved_run.status == RunStage.COMPLETED
        assert retrieved_run.dossier is not None
        assert retrieved_run.dossier.run_id == run_id
        assert len(retrieved_run.completed_task_ids) > 0
        assert retrieved_run.total_token_usage.total_tokens > 0

        # Checkpoints are persisted in shared_checkpoint_repo
        checkpoints = await shared_checkpoint_repo.list_checkpoints(run_id)
        assert len(checkpoints) > 0
        for cp in checkpoints:
            assert cp.verify_integrity() is True

    finally:
        await service_a.stop()


@pytest.mark.asyncio
async def test_durable_state_cancellation_persistence() -> None:
    """Test 2: Proves that cancellation persisted via service is durable and inspectable by fresh instances."""
    shared_run_repo = InMemoryRunRepository()
    shared_checkpoint_repo = InMemoryCheckpointRepository()

    service_a = ResearchService(
        run_repo=shared_run_repo,
        checkpoint_repo=shared_checkpoint_repo,
    )

    req = CreateRunRequest(
        query="Analyze edge quantum computing architectures",
        domain_tags=("quantum",),
    )
    summary = await service_a.create_and_start_run(req)
    run_id = summary.run_id

    # Cancel run via Service A
    cancel_resp = await service_a.cancel_run(run_id)
    assert cancel_resp.status == RunStage.CANCELLED

    # Fresh Service Instance B
    service_b = ResearchService(
        run_repo=shared_run_repo,
        checkpoint_repo=shared_checkpoint_repo,
    )
    assert run_id not in service_b._runs

    retrieved = await service_b.get_run(run_id)
    assert retrieved is not None
    assert retrieved.status == RunStage.CANCELLED
