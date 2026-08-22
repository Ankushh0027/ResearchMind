"""Unit tests for cooperative cancellation and graceful abort."""

import asyncio

import pytest

from app.common.enums import AgentRole, RunStage, TaskType
from app.orchestration.cancellation import CancellationToken
from app.orchestration.executor import DAGExecutor
from app.orchestration.worker import MockWorker, MockWorkerBehavior, WorkerRegistry
from app.state.models import DependencyEdge, ResearchGoal, ResearchPlan, SubtaskNode


@pytest.mark.asyncio
async def test_cancellation_before_execution() -> None:
    """Verify pre-cancelled token immediately terminates the run in CANCELLED stage."""
    token = CancellationToken()
    token.cancel("User clicked stop before run began")

    worker = MockWorker()
    node = SubtaskNode(
        subtask_id="t1",
        task_type=TaskType.WEB_SEARCH,
        objective="Task 1",
        assigned_role=AgentRole.RESEARCHER,
    )
    goal = ResearchGoal(goal_id="g1", query="Pre-cancel test")
    plan = ResearchPlan(
        plan_id="p_cancel",
        run_id="run_cancel_01",
        goal=goal,
        nodes={"t1": node},
        edges=(),
    )

    executor = DAGExecutor(worker_registry=WorkerRegistry(default_worker=worker))
    result = await executor.execute_plan(plan, cancellation_token=token)

    assert result.status == RunStage.CANCELLED
    assert "t1" in result.cancelled_task_ids
    assert len(worker.executed_requests) == 0


@pytest.mark.asyncio
async def test_cancellation_in_flight_stops_subsequent_tasks() -> None:
    """Verify cancelling during task 1 execution prevents task 2 from ever executing."""
    token = CancellationToken()

    # Worker delays on task 1, during which cancellation is triggered
    worker = MockWorker(default_behavior=MockWorkerBehavior(delay_seconds=0.05))

    node1 = SubtaskNode(
        subtask_id="task_1",
        task_type=TaskType.WEB_SEARCH,
        objective="Task 1",
        assigned_role=AgentRole.RESEARCHER,
    )
    node2 = SubtaskNode(
        subtask_id="task_2",
        task_type=TaskType.WEB_SEARCH,
        objective="Task 2",
        assigned_role=AgentRole.RESEARCHER,
    )
    edge = DependencyEdge(source_id="task_1", target_id="task_2")

    goal = ResearchGoal(goal_id="g1", query="In-flight cancel test")
    plan = ResearchPlan(
        plan_id="p_inflight",
        run_id="run_cancel_02",
        goal=goal,
        nodes={"task_1": node1, "task_2": node2},
        edges=(edge,),
    )

    async def cancel_later() -> None:
        await asyncio.sleep(0.01)
        token.cancel("Cancelled while task 1 in progress")

    executor = DAGExecutor(worker_registry=WorkerRegistry(default_worker=worker))

    _, result = await asyncio.gather(
        cancel_later(),
        executor.execute_plan(plan, cancellation_token=token),
    )

    assert result.status == RunStage.CANCELLED
    assert "task_2" not in result.completed_task_ids


def test_cancellation_token_idempotency() -> None:
    """Verify triggering cancel multiple times is safe and preserves initial reason."""
    token = CancellationToken()
    token.cancel("First reason")
    token.cancel("Second reason")

    assert token.is_cancelled is True
    assert token.reason == "First reason"
