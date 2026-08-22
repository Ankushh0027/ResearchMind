"""Unit tests for deadlock detection and graceful termination."""

import pytest

from app.common.enums import AgentRole, RunStage, TaskStatus, TaskType
from app.common.errors import DeadlockDetectedError
from app.orchestration.executor import DAGExecutor
from app.orchestration.scheduler import DAGScheduler
from app.orchestration.worker import MockWorker, MockWorkerBehavior, WorkerRegistry
from app.state.models import (
    DependencyEdge,
    ResearchGoal,
    ResearchPlan,
    SubtaskNode,
    TaskStateRecord,
)


def test_scheduler_detects_deadlock_on_unresolvable_dependencies() -> None:
    """Verify scheduler raises DeadlockDetectedError when tasks cannot progress."""
    node_a = SubtaskNode(subtask_id="A", task_type=TaskType.WEB_SEARCH, objective="A")
    node_b = SubtaskNode(subtask_id="B", task_type=TaskType.WEB_SEARCH, objective="B")
    edge = DependencyEdge(source_id="A", target_id="B")

    goal = ResearchGoal(goal_id="g1", query="Deadlock test")
    plan = ResearchPlan(
        plan_id="p_dl",
        run_id="run_dl_01",
        goal=goal,
        nodes={"A": node_a, "B": node_b},
        edges=(edge,),
    )

    # Initial state where A failed permanently and B is pending
    task_a_state = TaskStateRecord(
        subtask_id="A",
        run_id="run_dl_01",
        status=TaskStatus.FAILED,
        idempotency_key="idem_A",
    )
    task_b_state = TaskStateRecord(
        subtask_id="B",
        run_id="run_dl_01",
        status=TaskStatus.PENDING,
        idempotency_key="idem_B",
    )

    scheduler = DAGScheduler(
        plan=plan,
        initial_tasks={"A": task_a_state, "B": task_b_state},
    )

    with pytest.raises(DeadlockDetectedError) as exc_info:
        scheduler.check_and_raise_deadlock()

    assert "B" in exc_info.value.uncompleted_task_ids


@pytest.mark.asyncio
async def test_executor_handles_deadlock_without_infinite_wait() -> None:
    """Verify DAGExecutor terminates with RunStage.FAILED when a prerequisite fails permanently."""
    # Worker fails task A with non-retryable error
    worker = MockWorker(
        default_behavior=MockWorkerBehavior(
            should_fail=True,
            is_retryable_error=False,
            error_message="Non-retryable root failure",
        )
    )

    node_a = SubtaskNode(
        subtask_id="root_A",
        task_type=TaskType.WEB_SEARCH,
        objective="Root task",
        assigned_role=AgentRole.RESEARCHER,
    )
    node_b = SubtaskNode(
        subtask_id="child_B",
        task_type=TaskType.WEB_SEARCH,
        objective="Dependent child task",
        assigned_role=AgentRole.RESEARCHER,
    )
    edge = DependencyEdge(source_id="root_A", target_id="child_B")

    goal = ResearchGoal(goal_id="g1", query="Deadlock executor test")
    plan = ResearchPlan(
        plan_id="p_dl_exec",
        run_id="run_dl_exec_01",
        goal=goal,
        nodes={"root_A": node_a, "child_B": node_b},
        edges=(edge,),
    )

    executor = DAGExecutor(worker_registry=WorkerRegistry(default_worker=worker))
    result = await executor.execute_plan(plan)

    assert result.status == RunStage.FAILED
    assert "root_A" in result.failed_task_ids
    assert "child_B" not in result.completed_task_ids
