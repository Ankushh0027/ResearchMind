"""Unit tests for RetryPolicy calculation and retry decision predicates."""

import pytest

from app.common.enums import AgentRole, TaskType
from app.orchestration.contracts import AgentError
from app.orchestration.executor import DAGExecutor
from app.orchestration.retry import RetryPolicy
from app.orchestration.worker import MockWorker, MockWorkerBehavior, WorkerRegistry
from app.state.models import ResearchGoal, ResearchPlan, SubtaskNode


def test_exponential_backoff_delay_calculation() -> None:
    """Verify backoff delay calculation across attempts."""
    policy = RetryPolicy(
        max_attempts=4,
        base_delay_seconds=2.0,
        max_delay_seconds=10.0,
        exponential_factor=2.0,
    )

    # Attempt 1: 0.0 (initial attempt)
    assert policy.calculate_delay(1) == 0.0
    # Attempt 2: 2.0 * (2^0) = 2.0 (first retry)
    assert policy.calculate_delay(2) == 2.0
    # Attempt 3: 2.0 * (2^1) = 4.0 (second retry)
    assert policy.calculate_delay(3) == 4.0
    # Attempt 4: 2.0 * (2^2) = 8.0 (third retry)
    assert policy.calculate_delay(4) == 8.0
    # Attempt 5: 2.0 * (2^3) = 16.0 -> capped at 10.0
    assert policy.calculate_delay(5) == 10.0


def test_retry_eligibility_predicates() -> None:
    """Verify should_retry logic for retryable vs non-retryable errors."""
    policy = RetryPolicy(max_attempts=3)

    retryable_err = AgentError(
        error_code="RATE_LIMIT",
        error_type="QuotaError",
        message="Too many requests",
        is_retryable=True,
    )
    non_retryable_err = AgentError(
        error_code="INVALID_ARGUMENT",
        error_type="ValueError",
        message="Bad query format",
        is_retryable=False,
    )

    # Attempt 1 (under max_attempts)
    assert policy.should_retry(1, retryable_err) is True
    assert policy.should_retry(1, non_retryable_err) is False

    # Attempt 3 (at max_attempts -> no further retry)
    assert policy.should_retry(3, retryable_err) is False


@pytest.mark.asyncio
async def test_executor_retries_transient_failures_until_success() -> None:
    """Verify DAGExecutor retries transient failure and succeeds on 3rd attempt."""
    delays_recorded: list[float] = []

    async def fake_sleeper(seconds: float) -> None:
        delays_recorded.append(seconds)

    # Worker configured to fail on attempt 1 and 2, then succeed on 3
    worker = MockWorker(
        default_behavior=MockWorkerBehavior(
            fail_attempts_until=2,
            is_retryable_error=True,
            output_data={"result": "recovered_after_retries"},
        )
    )

    node = SubtaskNode(
        subtask_id="t_retry",
        task_type=TaskType.WEB_SEARCH,
        objective="Retry test task",
        max_retries=4,
        assigned_role=AgentRole.RESEARCHER,
    )
    goal = ResearchGoal(goal_id="g1", query="Retry execution test")
    plan = ResearchPlan(
        plan_id="p_retry",
        run_id="run_retry_01",
        goal=goal,
        nodes={"t_retry": node},
        edges=(),
    )

    policy = RetryPolicy(max_attempts=4, base_delay_seconds=1.0, exponential_factor=2.0)
    executor = DAGExecutor(
        worker_registry=WorkerRegistry(default_worker=worker),
        retry_policy=policy,
        sleeper=fake_sleeper,
    )

    result = await executor.execute_plan(plan)

    assert result.is_success is True
    assert "t_retry" in result.completed_task_ids
    assert result.task_outputs["t_retry"] == {"result": "recovered_after_retries"}
    # Two retry delays slept: attempt 2 (delay=1.0), attempt 3 (delay=2.0)
    assert delays_recorded == [1.0, 2.0]
