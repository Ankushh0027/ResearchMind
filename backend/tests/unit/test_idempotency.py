"""Unit tests for idempotency key semantics and duplicate execution prevention."""

import pytest

from app.common.enums import AgentRole, TaskType
from app.orchestration.executor import DAGExecutor
from app.orchestration.worker import MockWorker, MockWorkerBehavior, WorkerRegistry
from app.state.models import ResearchGoal, ResearchPlan, SubtaskNode


@pytest.mark.asyncio
async def test_idempotency_keys_recorded_per_attempt() -> None:
    """Verify each dispatched task attempt carries a deterministic idempotency key."""
    worker = MockWorker(
        default_behavior=MockWorkerBehavior(
            fail_attempts_until=1,
            is_retryable_error=True,
        )
    )

    node = SubtaskNode(
        subtask_id="t_idem",
        task_type=TaskType.WEB_SEARCH,
        objective="Idempotency test task",
        max_retries=3,
        assigned_role=AgentRole.RESEARCHER,
    )
    goal = ResearchGoal(goal_id="g1", query="Idempotency test")
    plan = ResearchPlan(
        plan_id="p_idem",
        run_id="run_idem_99",
        goal=goal,
        nodes={"t_idem": node},
        edges=(),
    )

    async def instant_sleeper(_: float) -> None:
        pass

    executor = DAGExecutor(
        worker_registry=WorkerRegistry(default_worker=worker),
        sleeper=instant_sleeper,
    )

    result = await executor.execute_plan(plan)
    assert result.is_success is True
    assert len(worker.executed_requests) == 2

    req1 = worker.executed_requests[0]
    req2 = worker.executed_requests[1]

    assert req1.idempotency_key == "idem_run_idem_99_t_idem_att1"
    assert req2.idempotency_key == "idem_run_idem_99_t_idem_att2"
    assert req1.attempt_number == 1
    assert req2.attempt_number == 2
