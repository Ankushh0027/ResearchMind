"""Domain exception hierarchy for ResearchMind."""

from typing import Any


class ResearchMindError(Exception):
    """Base exception for all domain-specific errors in ResearchMind."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class DAGValidationError(ResearchMindError):
    """Raised when a research plan graph violates DAG structural or safety constraints."""

    def __init__(
        self,
        message: str,
        error_code: str,
        violating_nodes: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged_details = details or {}
        merged_details["error_code"] = error_code
        merged_details["violating_nodes"] = violating_nodes or []
        super().__init__(message, merged_details)
        self.error_code = error_code
        self.violating_nodes = violating_nodes or []


class InvalidExecutionPlanError(DAGValidationError):
    """Raised when an execution plan fails validation prior to scheduling."""

    pass


class InvalidStateTransitionError(ResearchMindError):
    """Raised when an illegal lifecycle state transition is attempted."""

    def __init__(
        self,
        from_state: str,
        to_state: str,
        entity_id: str,
        reason: str | None = None,
    ) -> None:
        msg = f"Invalid state transition for entity '{entity_id}': '{from_state}' -> '{to_state}'"
        if reason:
            msg += f" ({reason})"
        super().__init__(
            msg,
            {
                "from_state": from_state,
                "to_state": to_state,
                "entity_id": entity_id,
                "reason": reason,
            },
        )
        self.from_state = from_state
        self.to_state = to_state
        self.entity_id = entity_id
        self.reason = reason


class PermissionDeniedError(ResearchMindError):
    """Raised when an agent role attempts to execute an unauthorized tool."""

    def __init__(
        self,
        agent_role: str,
        tool_permission: str,
        reason: str | None = None,
    ) -> None:
        msg = f"Permission denied: Agent role '{agent_role}' cannot access '{tool_permission}'"
        if reason:
            msg += f" ({reason})"
        super().__init__(
            msg,
            {
                "agent_role": agent_role,
                "tool_permission": tool_permission,
                "reason": reason,
            },
        )
        self.agent_role = agent_role
        self.tool_permission = tool_permission


class SchemaVersionError(ResearchMindError):
    """Raised when a schema payload version is unsupported or mismatched."""

    def __init__(self, current_version: str, expected_version: str) -> None:
        super().__init__(
            f"Schema version mismatch: current '{current_version}', expected '{expected_version}'",
            {
                "current_version": current_version,
                "expected_version": expected_version,
            },
        )
        self.current_version = current_version
        self.expected_version = expected_version


class IdempotencyConflictError(ResearchMindError):
    """Raised when a task with the same idempotency key is already completed or processing."""

    def __init__(self, idempotency_key: str, existing_status: str) -> None:
        super().__init__(
            f"Idempotency conflict for key '{idempotency_key}': existing status '{existing_status}'",
            {
                "idempotency_key": idempotency_key,
                "existing_status": existing_status,
            },
        )
        self.idempotency_key = idempotency_key
        self.existing_status = existing_status


class DuplicateExecutionError(IdempotencyConflictError):
    """Raised when duplicate execution of an already completed task is attempted."""

    pass


class CheckpointCorruptedError(ResearchMindError):
    """Raised when a checkpoint snapshot fails cryptographic hash integrity verification."""

    def __init__(
        self, snapshot_id: str, expected_hash: str, computed_hash: str
    ) -> None:
        super().__init__(
            f"Checkpoint integrity failure for snapshot '{snapshot_id}': hash mismatch",
            {
                "snapshot_id": snapshot_id,
                "expected_hash": expected_hash,
                "computed_hash": computed_hash,
            },
        )
        self.snapshot_id = snapshot_id
        self.expected_hash = expected_hash
        self.computed_hash = computed_hash


class CheckpointRecoveryError(ResearchMindError):
    """Raised when state recovery from a checkpoint snapshot fails."""

    def __init__(self, run_id: str, reason: str) -> None:
        super().__init__(
            f"Failed to recover checkpoint for run '{run_id}': {reason}",
            {"run_id": run_id, "reason": reason},
        )
        self.run_id = run_id
        self.reason = reason


class SchedulerError(ResearchMindError):
    """Raised when task scheduling encounters an unresolvable graph or state conflict."""

    pass


class DeadlockDetectedError(SchedulerError):
    """Raised when the execution graph reaches an unresolvable deadlock state."""

    def __init__(self, run_id: str, uncompleted_task_ids: list[str]) -> None:
        super().__init__(
            f"Deadlock detected in run '{run_id}': tasks {uncompleted_task_ids} cannot make progress",
            {"run_id": run_id, "uncompleted_task_ids": uncompleted_task_ids},
        )
        self.run_id = run_id
        self.uncompleted_task_ids = uncompleted_task_ids


class TaskTimeoutError(ResearchMindError):
    """Raised when a task execution exceeds its allocated timeout."""

    def __init__(self, subtask_id: str, timeout_seconds: int) -> None:
        super().__init__(
            f"Task '{subtask_id}' timed out after {timeout_seconds} seconds",
            {"subtask_id": subtask_id, "timeout_seconds": timeout_seconds},
        )
        self.subtask_id = subtask_id
        self.timeout_seconds = timeout_seconds


class WorkerExecutionError(ResearchMindError):
    """Raised when a worker fails with an unhandled exception during task execution."""

    def __init__(
        self, subtask_id: str, original_error: str, is_retryable: bool = True
    ) -> None:
        super().__init__(
            f"Worker execution failed for task '{subtask_id}': {original_error}",
            {
                "subtask_id": subtask_id,
                "original_error": original_error,
                "is_retryable": is_retryable,
            },
        )
        self.subtask_id = subtask_id
        self.original_error = original_error
        self.is_retryable = is_retryable


class RetryExhaustedError(ResearchMindError):
    """Raised when a task fails repeatedly and exceeds maximum retry attempts."""

    def __init__(self, subtask_id: str, attempts: int, last_error: str) -> None:
        super().__init__(
            f"Task '{subtask_id}' exhausted all {attempts} retry attempts. Last error: {last_error}",
            {"subtask_id": subtask_id, "attempts": attempts, "last_error": last_error},
        )
        self.subtask_id = subtask_id
        self.attempts = attempts
        self.last_error = last_error


class ExecutionCancelledError(ResearchMindError):
    """Raised when an operation is cancelled via cooperative cancellation token."""

    def __init__(self, entity_id: str, reason: str = "Operation was cancelled") -> None:
        super().__init__(
            f"Execution cancelled for '{entity_id}': {reason}",
            {"entity_id": entity_id, "reason": reason},
        )
        self.entity_id = entity_id
        self.reason = reason
