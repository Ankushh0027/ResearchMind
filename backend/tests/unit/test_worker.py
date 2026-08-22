"""Unit tests for worker protocol, MockWorker simulation, and WorkerRegistry."""

import pytest

from app.common.enums import AgentRole, TaskStatus, TaskType
from app.orchestration.cancellation import CancellationToken
from app.orchestration.contracts import AgentRequest, TokenUsage
from app.orchestration.worker import (
    MockWorker,
    MockWorkerBehavior,
    WorkerRegistry,
)


def _make_request(
    subtask_id: str = "t1", role: AgentRole = AgentRole.RESEARCHER
) -> AgentRequest:
    return AgentRequest(
        request_id="req_01",
        run_id="run_01",
        subtask_id=subtask_id,
        agent_role=role,
        task_type=TaskType.WEB_SEARCH,
        goal_context="Test goal",
        idempotency_key="idem_01",
        attempt_number=1,
    )


@pytest.mark.asyncio
async def test_mock_worker_success() -> None:
    """Verify MockWorker executes successfully and returns expected payload."""
    worker = MockWorker(
        worker_id="w-test",
        default_behavior=MockWorkerBehavior(
            output_data={"evidence": ["ev1", "ev2"]},
            token_usage=TokenUsage(
                prompt_tokens=50, completion_tokens=100, total_tokens=150
            ),
        ),
    )
    req = _make_request()
    envelope = await worker.execute(req)

    assert envelope.status == TaskStatus.COMPLETED
    assert envelope.worker_id == "w-test"
    assert envelope.response is not None
    assert envelope.response.output_data == {"evidence": ["ev1", "ev2"]}
    assert envelope.response.token_usage.total_tokens == 150
    assert envelope.error is None


@pytest.mark.asyncio
async def test_mock_worker_failure() -> None:
    """Verify MockWorker returns structured failure when configured."""
    worker = MockWorker(
        default_behavior=MockWorkerBehavior(
            should_fail=True,
            is_retryable_error=True,
            error_code="RATE_LIMIT",
            error_message="Quota exhausted",
        )
    )
    req = _make_request()
    envelope = await worker.execute(req)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "RATE_LIMIT"
    assert envelope.error.is_retryable is True


@pytest.mark.asyncio
async def test_mock_worker_exception() -> None:
    """Verify MockWorker propagates unhandled exceptions."""
    worker = MockWorker(
        default_behavior=MockWorkerBehavior(
            raise_exception=RuntimeError("Unrecoverable process fault")
        )
    )
    req = _make_request()
    with pytest.raises(RuntimeError, match="Unrecoverable process fault"):
        await worker.execute(req)


@pytest.mark.asyncio
async def test_mock_worker_cancellation() -> None:
    """Verify MockWorker respects pre-set cancellation token."""
    token = CancellationToken()
    token.cancel("Aborted by coordinator")

    worker = MockWorker(cancellation_token=token)
    req = _make_request()
    envelope = await worker.execute(req)

    assert envelope.status == TaskStatus.CANCELLED
    assert envelope.error is not None
    assert envelope.error.error_code == "CANCELLED"


def test_worker_registry_mapping() -> None:
    """Verify WorkerRegistry routes to registered worker or falls back to default."""
    default_w = MockWorker(worker_id="default")
    planner_w = MockWorker(worker_id="planner_worker")

    registry = WorkerRegistry(default_worker=default_w)
    registry.register(AgentRole.PLANNER, planner_w)

    assert registry.get_worker(AgentRole.PLANNER) is planner_w
    assert registry.get_worker(AgentRole.RESEARCHER) is default_w
