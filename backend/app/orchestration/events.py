"""Typed execution lifecycle events for ResearchMind orchestration."""

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.common.enums import AgentRole, TaskStatus, TaskType
from app.orchestration.contracts import TokenUsage


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _gen_id(prefix: str = "evt") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class ExecutionEvent(BaseModel):
    """Base model for all typed orchestration lifecycle events."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(
        default_factory=_gen_id, description="Unique event identifier"
    )
    run_id: str = Field(..., min_length=1, description="Associated research run ID")
    event_type: str = Field(..., min_length=1, description="Event classification name")
    timestamp: datetime = Field(default_factory=_utc_now)
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional contextual diagnostic metadata"
    )


class RunStartedEvent(ExecutionEvent):
    """Emitted when a research run begins execution."""

    event_type: str = "run_started"
    plan_id: str = Field(..., min_length=1)
    total_tasks: int = Field(..., ge=1)


class TaskScheduledEvent(ExecutionEvent):
    """Emitted when a subtask is queued and ready for worker allocation."""

    event_type: str = "task_scheduled"
    subtask_id: str = Field(..., min_length=1)
    task_type: TaskType = Field(...)
    assigned_role: AgentRole = Field(...)
    attempt: int = Field(default=1, ge=1)


class TaskStartedEvent(ExecutionEvent):
    """Emitted when an agent worker claims and begins executing a subtask."""

    event_type: str = "task_started"
    subtask_id: str = Field(..., min_length=1)
    worker_id: str = Field(..., min_length=1)
    attempt: int = Field(default=1, ge=1)


class TaskCompletedEvent(ExecutionEvent):
    """Emitted when a subtask execution succeeds."""

    event_type: str = "task_completed"
    subtask_id: str = Field(..., min_length=1)
    worker_id: str = Field(..., min_length=1)
    duration_ms: int = Field(..., ge=0)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    output_summary: str | None = Field(default=None)


class TaskFailedEvent(ExecutionEvent):
    """Emitted when a subtask execution encounters an error."""

    event_type: str = "task_failed"
    subtask_id: str = Field(..., min_length=1)
    worker_id: str = Field(..., min_length=1)
    attempt: int = Field(..., ge=1)
    error_code: str = Field(...)
    error_message: str = Field(...)
    is_retryable: bool = Field(default=True)


class TaskRetryScheduledEvent(ExecutionEvent):
    """Emitted when a failed subtask is scheduled for retry after backoff."""

    event_type: str = "task_retry_scheduled"
    subtask_id: str = Field(..., min_length=1)
    failed_attempt: int = Field(..., ge=1)
    next_attempt: int = Field(..., ge=2)
    delay_seconds: float = Field(..., ge=0.0)


class TaskCancelledEvent(ExecutionEvent):
    """Emitted when a subtask is cancelled due to parent cancellation or abort."""

    event_type: str = "task_cancelled"
    subtask_id: str = Field(..., min_length=1)
    reason: str = Field(default="Run cancelled")


class RunCompletedEvent(ExecutionEvent):
    """Emitted when all tasks in a research run complete successfully."""

    event_type: str = "run_completed"
    plan_id: str = Field(..., min_length=1)
    total_tasks_completed: int = Field(..., ge=0)
    duration_seconds: float = Field(..., ge=0.0)
    total_token_usage: TokenUsage = Field(default_factory=TokenUsage)


class RunFailedEvent(ExecutionEvent):
    """Emitted when a research run terminates with an unrecoverable failure."""

    event_type: str = "run_failed"
    error_type: str = Field(...)
    error_message: str = Field(...)
    failed_subtask_id: str | None = Field(default=None)


class RunCancelledEvent(ExecutionEvent):
    """Emitted when a research run is cancelled cooperatively."""

    event_type: str = "run_cancelled"
    reason: str = Field(default="User cancelled run")
    completed_tasks_count: int = Field(default=0, ge=0)


class DeadlockDetectedEvent(ExecutionEvent):
    """Emitted when the execution graph is unable to make progress due to a deadlock."""

    event_type: str = "deadlock_detected"
    uncompleted_task_ids: tuple[str, ...] = Field(default_factory=tuple)
    task_statuses: dict[str, TaskStatus] = Field(default_factory=dict)
