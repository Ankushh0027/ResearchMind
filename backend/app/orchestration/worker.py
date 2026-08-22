"""Worker abstractions, mock worker implementation, and worker registry."""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from app.common.enums import AgentRole, TaskStatus
from app.orchestration.cancellation import CancellationToken
from app.orchestration.contracts import (
    AgentError,
    AgentRequest,
    AgentResponse,
    TokenUsage,
    WorkerResponseEnvelope,
)
from app.orchestration.protocols import WorkerProtocol


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MockWorkerBehavior:
    """Configurable execution behavior for mock testing."""

    def __init__(
        self,
        should_fail: bool = False,
        is_retryable_error: bool = True,
        error_code: str = "MOCK_ERROR",
        error_message: str = "Simulated worker failure",
        raise_exception: Exception | None = None,
        delay_seconds: float = 0.0,
        output_data: dict[str, Any] | None = None,
        token_usage: TokenUsage | None = None,
        fail_attempts_until: int = 0,  # Fails until attempt > fail_attempts_until
    ) -> None:
        self.should_fail = should_fail
        self.is_retryable_error = is_retryable_error
        self.error_code = error_code
        self.error_message = error_message
        self.raise_exception = raise_exception
        self.delay_seconds = delay_seconds
        self.output_data = output_data or {"result": "mock_success"}
        self.token_usage = token_usage or TokenUsage(
            prompt_tokens=10, completion_tokens=20, total_tokens=30
        )
        self.fail_attempts_until = fail_attempts_until


class MockWorker(WorkerProtocol):
    """Deterministic, configurable mock worker for orchestration unit and property tests."""

    def __init__(
        self,
        worker_id: str = "mock-worker-01",
        default_behavior: MockWorkerBehavior | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> None:
        self.worker_id = worker_id
        self.default_behavior = default_behavior or MockWorkerBehavior()
        self.task_behaviors: dict[str, MockWorkerBehavior] = {}
        self.cancellation_token = cancellation_token
        self.executed_requests: list[AgentRequest] = []

    def set_task_behavior(self, subtask_id: str, behavior: MockWorkerBehavior) -> None:
        """Configure specific simulation behavior for a particular subtask ID."""
        self.task_behaviors[subtask_id] = behavior

    async def execute(self, request: AgentRequest) -> WorkerResponseEnvelope:
        """Execute mock task following configured simulation behaviors."""
        self.executed_requests.append(request)
        behavior = self.task_behaviors.get(request.subtask_id, self.default_behavior)

        # Check cooperative cancellation
        if self.cancellation_token and self.cancellation_token.is_cancelled:
            err = AgentError(
                error_code="CANCELLED",
                error_type="ExecutionCancelled",
                message=self.cancellation_token.reason or "Task cancelled",
                is_retryable=False,
            )
            return WorkerResponseEnvelope(
                envelope_id=f"env_{uuid.uuid4().hex[:12]}",
                dispatch_id=f"disp_{request.request_id}",
                run_id=request.run_id,
                subtask_id=request.subtask_id,
                status=TaskStatus.CANCELLED,
                error=err,
                worker_id=self.worker_id,
            )

        # Simulate work delay
        if behavior.delay_seconds > 0:
            await asyncio.sleep(behavior.delay_seconds)

        # Check for unhandled exception simulation
        if behavior.raise_exception is not None:
            raise behavior.raise_exception

        # Check attempt-based failure simulation
        should_fail = behavior.should_fail or (
            behavior.fail_attempts_until > 0
            and request.attempt_number <= behavior.fail_attempts_until
        )

        if should_fail:
            err = AgentError(
                error_code=behavior.error_code,
                error_type="WorkerError",
                message=behavior.error_message,
                is_retryable=behavior.is_retryable_error,
            )
            resp = AgentResponse(
                response_id=f"resp_{uuid.uuid4().hex[:12]}",
                request_id=request.request_id,
                run_id=request.run_id,
                subtask_id=request.subtask_id,
                agent_role=request.agent_role,
                output_data={},
                execution_time_ms=int(behavior.delay_seconds * 1000),
                token_usage=TokenUsage(),
                error=err,
            )
            return WorkerResponseEnvelope(
                envelope_id=f"env_{uuid.uuid4().hex[:12]}",
                dispatch_id=f"disp_{request.request_id}",
                run_id=request.run_id,
                subtask_id=request.subtask_id,
                status=TaskStatus.FAILED,
                response=resp,
                error=err,
                worker_id=self.worker_id,
            )

        # Successful execution
        resp = AgentResponse(
            response_id=f"resp_{uuid.uuid4().hex[:12]}",
            request_id=request.request_id,
            run_id=request.run_id,
            subtask_id=request.subtask_id,
            agent_role=request.agent_role,
            output_data=behavior.output_data,
            execution_time_ms=int(behavior.delay_seconds * 1000),
            token_usage=behavior.token_usage,
            error=None,
        )

        return WorkerResponseEnvelope(
            envelope_id=f"env_{uuid.uuid4().hex[:12]}",
            dispatch_id=f"disp_{request.request_id}",
            run_id=request.run_id,
            subtask_id=request.subtask_id,
            status=TaskStatus.COMPLETED,
            response=resp,
            error=None,
            worker_id=self.worker_id,
        )


class WorkerRegistry:
    """Registry routing task dispatches to appropriate agent workers by role."""

    def __init__(self, default_worker: WorkerProtocol | None = None) -> None:
        self._workers: dict[AgentRole, WorkerProtocol] = {}
        self._default_worker = default_worker or MockWorker()

    def register(self, role: AgentRole, worker: WorkerProtocol) -> None:
        """Register a worker for an agent role."""
        self._workers[role] = worker

    def get_worker(self, role: AgentRole) -> WorkerProtocol:
        """Resolve worker for an agent role, falling back to default worker if unmapped."""
        return self._workers.get(role, self._default_worker)
