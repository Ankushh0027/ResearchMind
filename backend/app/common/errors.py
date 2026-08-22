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
