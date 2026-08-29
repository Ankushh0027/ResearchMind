"""Execution contracts, request/response envelopes, and worker dispatch payloads."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.common.enums import AgentRole, TaskStatus, TaskType
from app.state.models import SubtaskNode


def _utc_now() -> datetime:
    return datetime.now(UTC)


class TokenUsage(BaseModel):
    """Resource token consumption tracking for LLM reasoning."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        if not isinstance(other, TokenUsage):
            return NotImplemented
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


class AgentError(BaseModel):
    """Structured error payload emitted when an agent execution fails."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    error_code: str = Field(
        ..., min_length=1, description="Machine-readable error identifier"
    )
    error_type: str = Field(
        ..., min_length=1, description="Exception category or class name"
    )
    message: str = Field(
        ..., min_length=1, description="Sanitized, human-readable error summary"
    )
    is_retryable: bool = Field(
        default=True, description="Whether the orchestrator should retry this task"
    )
    stack_trace_sanitized: str | None = Field(
        default=None, description="Sanitized diagnostic traceback without secrets"
    )
    timestamp: datetime = Field(default_factory=_utc_now)


class AgentRequest(BaseModel):
    """Standardized input payload sent to an autonomous agent worker."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str = Field(
        ..., min_length=1, description="Unique invocation identifier"
    )
    run_id: str = Field(..., min_length=1, description="Research run ID")
    subtask_id: str = Field(..., min_length=1, description="Target subtask node ID")
    agent_role: AgentRole = Field(..., description="Assigned agent role")
    task_type: TaskType = Field(..., description="Task operation type")
    goal_context: str = Field(
        ..., min_length=1, description="High-level research objective"
    )
    input_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured task inputs and dependency context",
    )
    idempotency_key: str = Field(
        ..., min_length=1, description="Deterministic idempotency token"
    )
    attempt_number: int = Field(
        default=1, ge=1, description="Execution attempt sequence number"
    )
    schema_version: str = Field(default="1.0.0", description="Contract schema version")
    created_at: datetime = Field(default_factory=_utc_now)


class AgentResponse(BaseModel):
    """Standardized result returned by an agent upon completing a task."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    response_id: str = Field(
        ..., min_length=1, description="Unique response identifier"
    )
    request_id: str = Field(..., min_length=1, description="Correlated request ID")
    run_id: str = Field(..., min_length=1, description="Research run ID")
    subtask_id: str = Field(..., min_length=1, description="Subtask ID")
    agent_role: AgentRole = Field(..., description="Agent role that executed the task")
    output_data: dict[str, Any] = Field(
        default_factory=dict, description="Structured execution results"
    )
    execution_time_ms: int = Field(
        default=0, ge=0, description="Task execution duration in milliseconds"
    )
    token_usage: TokenUsage = Field(
        default_factory=TokenUsage, description="Total tokens consumed"
    )
    error: AgentError | None = Field(
        default=None, description="Error record if execution failed"
    )
    created_at: datetime = Field(default_factory=_utc_now)

    @property
    def is_success(self) -> bool:
        """Check if execution completed without error."""
        return self.error is None


class TaskDispatchPayload(BaseModel):
    """Payload dispatched across message queue / worker bus to execute a subtask."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dispatch_id: str = Field(
        ..., min_length=1, description="Unique dispatch message ID"
    )
    run_id: str = Field(..., min_length=1, description="Research run ID")
    subtask: SubtaskNode = Field(..., description="Full subtask node definition")
    plan_version: int = Field(default=1, ge=1, description="Plan revision version")
    attempt: int = Field(default=1, ge=1, description="Attempt number")
    idempotency_key: str = Field(
        ..., min_length=1, description="Deterministic task idempotency key"
    )
    timeout_seconds: int = Field(
        default=120, ge=5, description="Worker execution deadline"
    )
    created_at: datetime = Field(default_factory=_utc_now)


class WorkerResponseEnvelope(BaseModel):
    """Envelope returned by worker back to orchestrator following task completion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    envelope_id: str = Field(..., min_length=1, description="Unique envelope ID")
    dispatch_id: str = Field(..., min_length=1, description="Correlated dispatch ID")
    run_id: str = Field(..., min_length=1, description="Research run ID")
    subtask_id: str = Field(..., min_length=1, description="Subtask ID")
    status: TaskStatus = Field(..., description="Final task status from worker")
    response: AgentResponse | None = Field(
        default=None, description="Detailed agent response if executed"
    )
    error: AgentError | None = Field(
        default=None, description="Worker-level error if task failed"
    )
    worker_id: str = Field(
        default="worker-local", description="Identifier of worker instance"
    )
    completed_at: datetime = Field(default_factory=_utc_now)
