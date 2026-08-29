"""Unit tests for Phase 7.1 LeaseSupervisor, stale reaper, checkpoint recovery, and concurrency protection."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.common.enums import RunStage
from app.jobs.in_memory import InMemoryJobPublisher, InMemoryJobQueue
from app.jobs.lease import InMemoryLeaseManager
from app.jobs.supervisor import (
    LeaseSupervisor,
    RecoveryStatus,
)
from app.orchestration.runtime import InMemoryCheckpointRepository
from app.persistence.in_memory import InMemoryRunRepository
from app.persistence.protocols import RunRecord
from app.state.models import ResearchGoal
from app.state.snapshot import CheckpointSnapshot, compute_state_hash


def _utc_now() -> datetime:
    return datetime.now(UTC)


@pytest.fixture
def run_repo() -> InMemoryRunRepository:
    return InMemoryRunRepository()


@pytest.fixture
def checkpoint_repo() -> InMemoryCheckpointRepository:
    return InMemoryCheckpointRepository()


@pytest.fixture
def job_queue() -> InMemoryJobQueue:
    return InMemoryJobQueue()


@pytest.fixture
def job_publisher(job_queue: InMemoryJobQueue) -> InMemoryJobPublisher:
    return InMemoryJobPublisher(job_queue)


@pytest.fixture
def lease_manager(run_repo: InMemoryRunRepository) -> InMemoryLeaseManager:
    return InMemoryLeaseManager(run_repo)


@pytest.fixture
def supervisor(
    run_repo: InMemoryRunRepository,
    checkpoint_repo: InMemoryCheckpointRepository,
    job_publisher: InMemoryJobPublisher,
    lease_manager: InMemoryLeaseManager,
) -> LeaseSupervisor:
    return LeaseSupervisor(
        run_repo=run_repo,
        checkpoint_repo=checkpoint_repo,
        publisher=job_publisher,
        lease_manager=lease_manager,
        max_recovery_attempts=3,
        supervisor_id="sup_test_01",
    )


class TestLeaseSupervisor:
    """Test suite for LeaseSupervisor failure detection and state recovery."""

    @pytest.mark.asyncio
    async def test_reap_stale_runs_finds_and_recovers_expired_lease(
        self,
        supervisor: LeaseSupervisor,
        run_repo: InMemoryRunRepository,
        checkpoint_repo: InMemoryCheckpointRepository,
        job_queue: InMemoryJobQueue,
    ) -> None:
        goal = ResearchGoal(
            goal_id="goal_stale_01", query="Quantum error mitigation analysis."
        )
        past_time = _utc_now() - timedelta(seconds=20)
        stale_record = RunRecord(
            run_id="run_stale_01",
            goal=goal,
            status=RunStage.RESEARCHING,
            worker_id="worker_crashed",
            lease_id="lease_old_111",
            lease_acquired_at=past_time - timedelta(seconds=60),
            lease_expires_at=past_time,
            heartbeat_at=past_time,
            recovery_attempt=0,
        )
        await run_repo.create_run(stale_record)

        # Save a valid checkpoint
        payload = {"run_id": "run_stale_01", "tasks": {}}
        ckpt = CheckpointSnapshot(
            snapshot_id="chk_run_stale_01_0001",
            run_id="run_stale_01",
            stage=RunStage.RESEARCHING,
            checkpoint_version=1,
            state_hash=compute_state_hash(payload),
            state_payload=payload,
        )
        await checkpoint_repo.save_checkpoint(ckpt)

        reports = await supervisor.reap_stale_runs()
        assert len(reports) == 1
        rep = reports[0]
        assert rep.run_id == "run_stale_01"
        assert rep.status == RecoveryStatus.RECOVERED
        assert rep.recovery_attempt == 1
        assert rep.checkpoint_id == "chk_run_stale_01_0001"
        assert rep.checkpoint_version == 1
        assert rep.republished is True

        # Check updated record in repository
        updated_rec = await run_repo.get_run("run_stale_01")
        assert updated_rec is not None
        assert updated_rec.recovery_attempt == 1
        assert updated_rec.last_checkpoint_id == "chk_run_stale_01_0001"
        assert updated_rec.lease_id is None

        # Check republished job in queue
        assert job_queue.size() == 1

    @pytest.mark.asyncio
    async def test_recovery_max_attempts_exhausted(
        self,
        supervisor: LeaseSupervisor,
        run_repo: InMemoryRunRepository,
        job_queue: InMemoryJobQueue,
    ) -> None:
        goal = ResearchGoal(
            goal_id="goal_exhaust_02",
            query="Analyze fault-tolerant quantum algorithms.",
        )
        past_time = _utc_now() - timedelta(seconds=10)
        exhausted_record = RunRecord(
            run_id="run_exhaust_02",
            goal=goal,
            status=RunStage.RESEARCHING,
            worker_id="worker_crashed_3",
            lease_id="lease_old_333",
            lease_expires_at=past_time,
            recovery_attempt=3,  # Already at max 3
        )
        await run_repo.create_run(exhausted_record)

        report = await supervisor.recover_run("run_exhaust_02")
        assert report.status == RecoveryStatus.EXHAUSTED
        assert report.republished is False

        updated_rec = await run_repo.get_run("run_exhaust_02")
        assert updated_rec is not None
        assert updated_rec.status == RunStage.FAILED
        assert "exhausted" in (updated_rec.error or "").lower()
        assert job_queue.size() == 0

    @pytest.mark.asyncio
    async def test_recovery_cancelled_run_marks_cancelled_without_republish(
        self,
        supervisor: LeaseSupervisor,
        run_repo: InMemoryRunRepository,
        job_queue: InMemoryJobQueue,
    ) -> None:
        goal = ResearchGoal(
            goal_id="goal_canc_03", query="Cancelled inquiry investigation."
        )
        past_time = _utc_now() - timedelta(seconds=15)
        cancelled_record = RunRecord(
            run_id="run_canc_03",
            goal=goal,
            status=RunStage.RESEARCHING,
            worker_id="worker_crashed",
            lease_id="lease_canc_123",
            lease_expires_at=past_time,
            is_cancelled=True,
            cancellation_reason="User cancelled before recovery",
        )
        await run_repo.create_run(cancelled_record)

        report = await supervisor.recover_run("run_canc_03")
        assert report.status == RecoveryStatus.CANCELLED
        assert report.republished is False

        updated_rec = await run_repo.get_run("run_canc_03")
        assert updated_rec is not None
        assert updated_rec.status == RunStage.CANCELLED
        assert job_queue.size() == 0

    @pytest.mark.asyncio
    async def test_concurrent_supervisors_duplicate_claim_protection(
        self,
        run_repo: InMemoryRunRepository,
        checkpoint_repo: InMemoryCheckpointRepository,
        job_publisher: InMemoryJobPublisher,
        lease_manager: InMemoryLeaseManager,
        job_queue: InMemoryJobQueue,
    ) -> None:
        goal = ResearchGoal(goal_id="goal_race_04", query="Concurrency test inquiry.")
        past_time = _utc_now() - timedelta(seconds=10)
        stale_record = RunRecord(
            run_id="run_race_04",
            goal=goal,
            status=RunStage.RESEARCHING,
            worker_id="worker_crashed",
            lease_id="lease_race_111",
            lease_expires_at=past_time,
            recovery_attempt=0,
        )
        await run_repo.create_run(stale_record)

        sup_alpha = LeaseSupervisor(
            run_repo=run_repo,
            checkpoint_repo=checkpoint_repo,
            publisher=job_publisher,
            lease_manager=lease_manager,
            max_recovery_attempts=3,
            supervisor_id="sup_alpha",
        )
        sup_beta = LeaseSupervisor(
            run_repo=run_repo,
            checkpoint_repo=checkpoint_repo,
            publisher=job_publisher,
            lease_manager=lease_manager,
            max_recovery_attempts=3,
            supervisor_id="sup_beta",
        )

        # Execute concurrent recovery claims
        results = await asyncio.gather(
            sup_alpha.recover_run("run_race_04"),
            sup_beta.recover_run("run_race_04"),
        )

        statuses = [r.status for r in results]
        assert RecoveryStatus.RECOVERED in statuses
        assert RecoveryStatus.SKIPPED in statuses
        # Exactly one job republished in queue
        assert job_queue.size() == 1
