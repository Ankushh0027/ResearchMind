"""Unit tests for checkpoint persistence, state recovery, and partial execution resume."""

import pytest

from app.common.enums import AgentRole, TaskStatus, TaskType
from app.common.errors import CheckpointCorruptedError
from app.orchestration.executor import DAGExecutor
from app.orchestration.runtime import InMemoryCheckpointRepository
from app.orchestration.worker import MockWorker, WorkerRegistry
from app.state.models import (
    DependencyEdge,
    ResearchGoal,
    ResearchPlan,
    RunState,
    SubtaskNode,
    TaskStateRecord,
)
from app.state.snapshot import create_checkpoint


@pytest.mark.asyncio
async def test_checkpoint_saved_during_execution() -> None:
    """Verify DAGExecutor saves checkpoint snapshots to the repository as tasks finish."""
    repo = InMemoryCheckpointRepository()
    node = SubtaskNode(
        subtask_id="t1",
        task_type=TaskType.WEB_SEARCH,
        objective="Task 1",
        assigned_role=AgentRole.RESEARCHER,
    )
    goal = ResearchGoal(goal_id="g1", query="Checkpoint test")
    plan = ResearchPlan(
        plan_id="p1",
        run_id="run_chk_01",
        goal=goal,
        nodes={"t1": node},
        edges=(),
    )

    executor = DAGExecutor(checkpoint_repo=repo)
    result = await executor.execute_plan(plan)
    assert result.is_success is True

    snapshots = await repo.list_checkpoints("run_chk_01")
    assert len(snapshots) >= 1
    assert snapshots[-1].verify_integrity() is True


@pytest.mark.asyncio
async def test_resume_from_checkpoint_skips_already_completed_tasks() -> None:
    """Verify resuming from checkpoint skips already completed task A and executes pending task B."""
    node_a = SubtaskNode(
        subtask_id="task_A",
        task_type=TaskType.WEB_SEARCH,
        objective="Task A (already completed)",
        assigned_role=AgentRole.RESEARCHER,
    )
    node_b = SubtaskNode(
        subtask_id="task_B",
        task_type=TaskType.WEB_SEARCH,
        objective="Task B (pending)",
        assigned_role=AgentRole.RESEARCHER,
    )
    edge = DependencyEdge(source_id="task_A", target_id="task_B")

    goal = ResearchGoal(goal_id="g1", query="Resume test")
    plan = ResearchPlan(
        plan_id="p_resume",
        run_id="run_resume_01",
        goal=goal,
        nodes={"task_A": node_a, "task_B": node_b},
        edges=(edge,),
    )

    # Synthetic run state where task_A is COMPLETED, task_B is PENDING
    task_a_state = TaskStateRecord(
        subtask_id="task_A",
        run_id="run_resume_01",
        status=TaskStatus.COMPLETED,
        idempotency_key="idem_task_A",
    )
    task_b_state = TaskStateRecord(
        subtask_id="task_B",
        run_id="run_resume_01",
        status=TaskStatus.PENDING,
        idempotency_key="idem_task_B",
    )

    prior_state = RunState(
        run_id="run_resume_01",
        goal=goal,
        active_plan=plan,
        tasks={"task_A": task_a_state, "task_B": task_b_state},
    )
    checkpoint = create_checkpoint(prior_state)

    worker = MockWorker()
    executor = DAGExecutor(worker_registry=WorkerRegistry(default_worker=worker))

    result = await executor.resume_from_checkpoint(checkpoint)

    assert result.is_success is True
    assert set(result.completed_task_ids) == {"task_A", "task_B"}
    # Worker should only have been invoked for task_B!
    assert len(worker.executed_requests) == 1
    assert worker.executed_requests[0].subtask_id == "task_B"


@pytest.mark.asyncio
async def test_corrupted_checkpoint_recovery_rejected() -> None:
    """Verify tampered checkpoint raises CheckpointCorruptedError upon resumption."""
    goal = ResearchGoal(goal_id="g1", query="Corrupted test")
    plan = ResearchPlan(
        plan_id="p_corrupt",
        run_id="run_corrupt",
        goal=goal,
        nodes={
            "t1": SubtaskNode(
                subtask_id="t1", task_type=TaskType.WEB_SEARCH, objective="T1"
            )
        },
        edges=(),
    )
    state = RunState(run_id="run_corrupt", goal=goal, active_plan=plan)
    valid_chk = create_checkpoint(state)

    # Mutate payload without updating hash
    tampered_payload = dict(valid_chk.state_payload)
    tampered_payload["run_id"] = "tampered_run_id"
    corrupted_chk = valid_chk.model_copy(update={"state_payload": tampered_payload})

    executor = DAGExecutor()
    with pytest.raises(CheckpointCorruptedError):
        await executor.resume_from_checkpoint(corrupted_chk)
