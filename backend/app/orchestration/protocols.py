"""Framework-agnostic protocols and interfaces for orchestration components."""

from typing import Protocol, runtime_checkable

from app.orchestration.contracts import (
    AgentRequest,
    TokenUsage,
    WorkerResponseEnvelope,
)
from app.state.snapshot import CheckpointSnapshot


@runtime_checkable
class WorkerProtocol(Protocol):
    """Protocol for agent workers executing research subtasks."""

    async def execute(self, request: AgentRequest) -> WorkerResponseEnvelope:
        """Execute a subtask request and return a standardized response envelope."""
        ...


@runtime_checkable
class CheckpointRepositoryProtocol(Protocol):
    """Protocol for persisting and restoring run checkpoints."""

    async def save_checkpoint(self, snapshot: CheckpointSnapshot) -> None:
        """Persist an immutable checkpoint snapshot."""
        ...

    async def load_latest_checkpoint(self, run_id: str) -> CheckpointSnapshot | None:
        """Retrieve the latest checkpoint snapshot for a run ID."""
        ...

    async def list_checkpoints(self, run_id: str) -> list[CheckpointSnapshot]:
        """List all checkpoint snapshots recorded for a run ID."""
        ...


@runtime_checkable
class EventSinkProtocol(Protocol):
    """Protocol for publishing or capturing typed execution lifecycle events."""

    async def emit(self, event: object) -> None:
        """Emit an execution lifecycle event."""
        ...


@runtime_checkable
class ObservabilityHooksProtocol(Protocol):
    """Protocol for metric and telemetry collectors observing execution lifecycles."""

    async def on_run_started(self, run_id: str, plan_id: str) -> None:
        """Hook called when a research run begins execution."""
        ...

    async def on_run_completed(
        self, run_id: str, duration_seconds: float, token_usage: TokenUsage
    ) -> None:
        """Hook called when a research run reaches completion."""
        ...

    async def on_task_started(self, run_id: str, subtask_id: str, attempt: int) -> None:
        """Hook called when a subtask worker begins execution."""
        ...

    async def on_task_completed(
        self,
        run_id: str,
        subtask_id: str,
        duration_ms: int,
        token_usage: TokenUsage,
    ) -> None:
        """Hook called when a subtask completes successfully."""
        ...

    async def on_task_failed(
        self,
        run_id: str,
        subtask_id: str,
        attempt: int,
        error: str,
        is_retryable: bool,
    ) -> None:
        """Hook called when a subtask execution fails."""
        ...

    async def on_task_retried(
        self,
        run_id: str,
        subtask_id: str,
        next_attempt: int,
        delay_seconds: float,
    ) -> None:
        """Hook called when a retry backoff delay is scheduled for a subtask."""
        ...
