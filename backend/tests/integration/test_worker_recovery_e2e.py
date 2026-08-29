"""End-to-end integration tests simulating worker crashes, checkpoint restoration, and recovery lifecycles."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.common.enums import AgentRole, RunStage, TaskStatus, TaskType
from app.jobs.in_memory import (
    InMemoryJobPublisher,
    InMemoryJobQueue,
)
from app.jobs.lease import InMemoryLeaseManager
from app.jobs.protocols import JobStatus
from app.jobs.supervisor import LeaseSupervisor, RecoveryStatus
from app.jobs.worker import ResearchJobWorker
from app.orchestration.router import create_default_worker_router
from app.orchestration.runtime import InMemoryCheckpointRepository
from app.persistence.in_memory import InMemoryRunRepository
from app.persistence.protocols import RunRecord
from app.state.models import (
    DependencyEdge,
    ResearchGoal,
    ResearchPlan,
    RunState,
    SubtaskNode,
    TaskStateRecord,
)
from app.state.snapshot import create_checkpoint
from app.storage.in_memory import InMemoryArtifactStorage


def _utc_now() -> datetime:
    return datetime.now(UTC)


@pytest.fixture
def run_repo() -> InMemoryRunRepository:
    return InMemoryRunRepository()


@pytest.fixture
def checkpoint_repo() -> InMemoryCheckpointRepository:
    return InMemoryCheckpointRepository()


@pytest.fixture
def artifact_storage() -> InMemoryArtifactStorage:
    return InMemoryArtifactStorage()


@pytest.fixture
def job_queue() -> InMemoryJobQueue:
    return InMemoryJobQueue()


@pytest.fixture
def job_publisher(job_queue: InMemoryJobQueue) -> InMemoryJobPublisher:
    return InMemoryJobPublisher(job_queue)


@pytest.fixture
def lease_manager(run_repo: InMemoryRunRepository) -> InMemoryLeaseManager:
    return InMemoryLeaseManager(run_repo)


class TestWorkerRecoveryE2E:
    """Integration test suite verifying automated crash detection and checkpoint recovery."""

    @pytest.mark.asyncio
    async def test_worker_crash_and_transparent_recovery(
        self,
        run_repo: InMemoryRunRepository,
        checkpoint_repo: InMemoryCheckpointRepository,
        artifact_storage: InMemoryArtifactStorage,
        job_queue: InMemoryJobQueue,
        job_publisher: InMemoryJobPublisher,
        lease_manager: InMemoryLeaseManager,
    ) -> None:
        # 1. Create Initial Run
        goal = ResearchGoal(
            goal_id="goal_e2e_crash_01",
            query="Explore topological invariants in Chern insulators.",
            domain_tags=("condensed-matter", "quantum"),
            max_subtasks=10,
        )
        record = RunRecord(
            run_id="run_e2e_crash_01",
            goal=goal,
            status=RunStage.RESEARCHING,
        )
        await run_repo.create_run(record)

        # 2. Worker A starts job, acquires lease, saves a checkpoint, and simulates crash
        worker_a = ResearchJobWorker(
            router=create_default_worker_router(),
            run_repo=run_repo,
            checkpoint_repo=checkpoint_repo,
            artifact_storage=artifact_storage,
            lease_manager=lease_manager,
            worker_id="worker_instance_alpha",
        )

        lease_a = await lease_manager.acquire_lease(
            run_id="run_e2e_crash_01",
            worker_id="worker_instance_alpha",
            duration_seconds=0.1,  # Short lease to expire quickly
        )
        assert lease_a is not None

        # Simulate checkpoint creation by Worker A during execution
        plan_nodes = {
            "task_01": SubtaskNode(
                subtask_id="task_01",
                objective="Search topological invariants literature.",
                assigned_role=AgentRole.RESEARCHER,
                task_type=TaskType.ACADEMIC_SEARCH,
            ),
            "task_02": SubtaskNode(
                subtask_id="task_02",
                objective="Analyze Chern numbers and Hall conductance literature.",
                assigned_role=AgentRole.RESEARCHER,
                task_type=TaskType.ACADEMIC_SEARCH,
            ),
        }
        edges_list: list[DependencyEdge] = []
        worker_a._ensure_complete_research_mesh(plan_nodes, edges_list, goal.query)

        plan = ResearchPlan(
            plan_id="plan_e2e_01",
            run_id="run_e2e_crash_01",
            goal=goal,
            nodes=plan_nodes,
            edges=tuple(edges_list),
        )

        task_states = {
            nid: TaskStateRecord(
                subtask_id=nid,
                run_id="run_e2e_crash_01",
                status=TaskStatus.COMPLETED if nid == "task_01" else TaskStatus.PENDING,
                idempotency_key=f"idem_{nid}",
            )
            for nid in plan_nodes
        }
        run_state = RunState(
            run_id="run_e2e_crash_01",
            goal=goal,
            current_stage=RunStage.RESEARCHING,
            active_plan=plan,
            tasks=task_states,
        )
        ckpt_a = create_checkpoint(run_state)
        await checkpoint_repo.save_checkpoint(ckpt_a)

        # Worker A disappears and lease expires
        await asyncio.sleep(0.15)
        assert lease_manager.is_lease_expired(lease_a)

        # 3. Supervisor detects stale lease, recovers checkpoint, and republishes
        supervisor = LeaseSupervisor(
            run_repo=run_repo,
            checkpoint_repo=checkpoint_repo,
            publisher=job_publisher,
            lease_manager=lease_manager,
            max_recovery_attempts=3,
            supervisor_id="sup_daemon_01",
        )

        reports = await supervisor.reap_stale_runs()
        assert len(reports) == 1
        assert reports[0].status == RecoveryStatus.RECOVERED
        assert reports[0].republished is True
        assert reports[0].checkpoint_id == ckpt_a.snapshot_id
        assert job_queue.size() == 1

        # 4. Worker B ingests republished job and resumes execution
        worker_b = ResearchJobWorker(
            router=create_default_worker_router(),
            run_repo=run_repo,
            checkpoint_repo=checkpoint_repo,
            artifact_storage=artifact_storage,
            lease_manager=lease_manager,
            worker_id="worker_instance_beta",
        )

        republished_envelope = await job_queue.get()
        assert republished_envelope is not None
        assert republished_envelope.attempt == 1

        final_envelope = await worker_b.handle_job(republished_envelope)
        assert final_envelope.status == JobStatus.COMPLETED

        # 5. Verify final repository state
        final_record = await run_repo.get_run("run_e2e_crash_01")
        assert final_record is not None
        assert final_record.status == RunStage.COMPLETED
        assert final_record.recovery_attempt == 1
        assert final_record.dossier is not None

    @pytest.mark.asyncio
    async def test_recovery_attempts_exhaustion_on_persistent_crashes(
        self,
        run_repo: InMemoryRunRepository,
        checkpoint_repo: InMemoryCheckpointRepository,
        job_publisher: InMemoryJobPublisher,
        lease_manager: InMemoryLeaseManager,
    ) -> None:
        goal = ResearchGoal(
            goal_id="goal_e2e_exhaust_02", query="Stress test permanent crash handling."
        )
        record = RunRecord(run_id="run_e2e_exhaust_02", goal=goal)
        await run_repo.create_run(record)

        supervisor = LeaseSupervisor(
            run_repo=run_repo,
            checkpoint_repo=checkpoint_repo,
            publisher=job_publisher,
            lease_manager=lease_manager,
            max_recovery_attempts=2,  # Max 2 attempts
            supervisor_id="sup_test_exhaust",
        )

        # Attempt 1: Simulate crash & recovery
        past_time = _utc_now() - timedelta(seconds=10)
        rec = await run_repo.get_run("run_e2e_exhaust_02")
        assert rec is not None
        await run_repo.update_run(
            rec.with_updates(
                status=RunStage.RESEARCHING,
                worker_id="worker_1",
                lease_id="lease_1",
                lease_expires_at=past_time,
                recovery_attempt=0,
            )
        )
        rep1 = await supervisor.recover_run("run_e2e_exhaust_02")
        assert rep1.status == RecoveryStatus.RECOVERED
        assert rep1.recovery_attempt == 1

        # Attempt 2: Simulate 2nd crash & recovery
        rec2 = await run_repo.get_run("run_e2e_exhaust_02")
        assert rec2 is not None
        await run_repo.update_run(
            rec2.with_updates(
                status=RunStage.RESEARCHING,
                worker_id="worker_2",
                lease_id="lease_2",
                lease_expires_at=past_time,
            )
        )
        rep2 = await supervisor.recover_run("run_e2e_exhaust_02")
        assert rep2.status == RecoveryStatus.RECOVERED
        assert rep2.recovery_attempt == 2

        # Attempt 3: Exceeds max 2 attempts -> Permanently FAILED
        rec3 = await run_repo.get_run("run_e2e_exhaust_02")
        assert rec3 is not None
        await run_repo.update_run(
            rec3.with_updates(
                status=RunStage.RESEARCHING,
                worker_id="worker_3",
                lease_id="lease_3",
                lease_expires_at=past_time,
            )
        )
        rep3 = await supervisor.recover_run("run_e2e_exhaust_02")
        assert rep3.status == RecoveryStatus.EXHAUSTED
        assert rep3.republished is False

        final_rec = await run_repo.get_run("run_e2e_exhaust_02")
        assert final_rec is not None
        assert final_rec.status == RunStage.FAILED
        assert "exhausted" in (final_rec.error or "").lower()

    @pytest.mark.asyncio
    async def test_cancellation_interception_during_recovery(
        self,
        run_repo: InMemoryRunRepository,
        checkpoint_repo: InMemoryCheckpointRepository,
        job_queue: InMemoryJobQueue,
        job_publisher: InMemoryJobPublisher,
        lease_manager: InMemoryLeaseManager,
    ) -> None:
        goal = ResearchGoal(
            goal_id="goal_e2e_cancel_03", query="Inquiry cancelled before recovery."
        )
        past_time = _utc_now() - timedelta(seconds=10)
        record = RunRecord(
            run_id="run_e2e_cancel_03",
            goal=goal,
            status=RunStage.RESEARCHING,
            worker_id="worker_dead",
            lease_id="lease_dead",
            lease_expires_at=past_time,
            is_cancelled=True,
            cancellation_reason="User cancelled during outage",
        )
        await run_repo.create_run(record)

        supervisor = LeaseSupervisor(
            run_repo=run_repo,
            checkpoint_repo=checkpoint_repo,
            publisher=job_publisher,
            lease_manager=lease_manager,
            max_recovery_attempts=3,
        )

        reports = await supervisor.reap_stale_runs()
        assert len(reports) == 1
        assert reports[0].status == RecoveryStatus.CANCELLED
        assert reports[0].republished is False
        assert job_queue.size() == 0

        final_rec = await run_repo.get_run("run_e2e_cancel_03")
        assert final_rec is not None
        assert final_rec.status == RunStage.CANCELLED
