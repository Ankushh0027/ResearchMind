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


class EvidenceValidationError(ResearchMindError):
    """Raised when evidence content, provenance, or identifiers fail validation."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details)


class RAGError(ResearchMindError):
    """Base domain exception for RAG memory, vector storage, and embedding errors."""

    pass


class VectorDimensionMismatchError(RAGError):
    """Raised when a vector dimension does not match the configured store or model dimension."""

    def __init__(
        self,
        expected_dimension: int,
        actual_dimension: int,
        entity_id: str | None = None,
    ) -> None:
        msg = f"Vector dimension mismatch: expected {expected_dimension}, got {actual_dimension}"
        if entity_id:
            msg += f" for entity '{entity_id}'"
        super().__init__(
            msg,
            {
                "expected_dimension": expected_dimension,
                "actual_dimension": actual_dimension,
                "entity_id": entity_id,
            },
        )
        self.expected_dimension = expected_dimension
        self.actual_dimension = actual_dimension
        self.entity_id = entity_id


class CollectionNotFoundError(RAGError):
    """Raised when an operation targets a non-existent vector collection."""

    def __init__(self, collection_name: str) -> None:
        super().__init__(
            f"Vector collection '{collection_name}' not found",
            {"collection_name": collection_name},
        )
        self.collection_name = collection_name


class EmptyVectorQueryError(RAGError):
    """Raised when an empty or zero-norm query vector is submitted."""

    def __init__(
        self, message: str = "Query vector must not be empty or zero-norm"
    ) -> None:
        super().__init__(message)


class EvidenceIngestionError(ResearchMindError):
    """Base domain exception for evidence ingestion pipeline errors."""

    def __init__(
        self,
        message: str,
        code: str = "INGESTION_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        merged_details = details or {}
        merged_details["error_code"] = code
        super().__init__(message, merged_details)
        self.code = code


class InvalidSourceURLError(EvidenceIngestionError):
    """Raised when an evidence source URL or DOI URI is invalid or uses a disallowed scheme."""

    def __init__(
        self,
        source_url: str,
        reason: str = "Invalid or disallowed URI scheme",
    ) -> None:
        super().__init__(
            f"Invalid source URL '{source_url}': {reason}",
            code="INVALID_URI_SCHEME",
            details={"source_url": source_url, "reason": reason},
        )
        self.source_url = source_url
        self.reason = reason


class OversizedContentError(EvidenceIngestionError):
    """Raised when evidence content exceeds the maximum allowed payload byte size."""

    def __init__(
        self,
        byte_count: int,
        max_bytes: int,
    ) -> None:
        super().__init__(
            f"Evidence content size ({byte_count} bytes) exceeds limit ({max_bytes} bytes)",
            code="OVERSIZED_CONTENT",
            details={"byte_count": byte_count, "max_bytes": max_bytes},
        )
        self.byte_count = byte_count
        self.max_bytes = max_bytes


class DuplicateEvidenceError(EvidenceIngestionError):
    """Raised when duplicate evidence is encountered in strict ingestion mode."""

    def __init__(
        self,
        content_hash: str,
        run_id: str,
    ) -> None:
        super().__init__(
            f"Duplicate evidence detected for hash '{content_hash}' in run '{run_id}'",
            code="DUPLICATE_EVIDENCE",
            details={"content_hash": content_hash, "run_id": run_id},
        )
        self.content_hash = content_hash
        self.run_id = run_id


class ClaimExtractionError(ResearchMindError):
    """Base domain exception for claim extraction and factual analysis errors."""

    def __init__(
        self,
        message: str,
        code: str = "CLAIM_EXTRACTION_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        merged_details = details or {}
        merged_details["error_code"] = code
        super().__init__(message, merged_details)
        self.code = code


class UngroundedClaimError(ClaimExtractionError):
    """Raised when an extracted claim lacks supporting evidence backlinks."""

    def __init__(
        self,
        claim_statement: str,
        reason: str = "Claim has no supporting evidence IDs",
    ) -> None:
        super().__init__(
            f"Ungrounded claim: '{claim_statement}' - {reason}",
            code="UNGROUNDED_CLAIM",
            details={"claim_statement": claim_statement, "reason": reason},
        )
        self.claim_statement = claim_statement
        self.reason = reason


class InvalidClaimError(ClaimExtractionError):
    """Raised when claim parameters or confidence scores are invalid."""

    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="INVALID_CLAIM", details=details)


class AnalysisError(ResearchMindError):
    """Base domain exception for analyst agent and synthesis errors."""

    def __init__(
        self,
        message: str,
        code: str = "ANALYSIS_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        merged_details = details or {}
        merged_details["error_code"] = code
        super().__init__(message, merged_details)
        self.code = code


class UngroundedFindingError(AnalysisError):
    """Raised when a thematic finding lacks supporting claim or evidence IDs."""

    def __init__(
        self,
        finding_title: str,
        reason: str = "Finding has no supporting claim or evidence IDs",
    ) -> None:
        super().__init__(
            f"Ungrounded finding: '{finding_title}' - {reason}",
            code="UNGROUNDED_FINDING",
            details={"finding_title": finding_title, "reason": reason},
        )
        self.finding_title = finding_title
        self.reason = reason


class ContradictionDetectionError(ResearchMindError):
    """Base domain exception for contradiction and conflict detection errors."""

    def __init__(
        self,
        message: str,
        code: str = "CONTRADICTION_DETECTION_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        merged_details = details or {}
        merged_details["error_code"] = code
        super().__init__(message, merged_details)
        self.code = code


class InvalidContradictionError(ContradictionDetectionError):
    """Raised when contradiction detection parameters or inputs are invalid."""

    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="INVALID_CONTRADICTION", details=details)


class VerificationError(ResearchMindError):
    """Base domain exception for verifier agent and grounding audit errors."""

    def __init__(
        self,
        message: str,
        code: str = "VERIFICATION_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        merged_details = details or {}
        merged_details["error_code"] = code
        super().__init__(message, merged_details)
        self.code = code


class UngroundedCitationError(VerificationError):
    """Raised when a citation references a non-existent or ungrounded evidence record."""

    def __init__(
        self,
        evidence_id: str,
        reason: str = "Referenced evidence record does not exist in evidence pool",
    ) -> None:
        super().__init__(
            f"Ungrounded citation for evidence '{evidence_id}': {reason}",
            code="UNGROUNDED_CITATION",
            details={"evidence_id": evidence_id, "reason": reason},
        )
        self.evidence_id = evidence_id
        self.reason = reason


class EvaluationError(ResearchMindError):
    """Base domain exception for evaluator agent and quality audit errors."""

    def __init__(
        self,
        message: str,
        code: str = "EVALUATION_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        merged_details = details or {}
        merged_details["error_code"] = code
        super().__init__(message, merged_details)
        self.code = code


class ReportingError(ResearchMindError):
    """Base domain exception for reporter agent and research dossier compilation errors."""

    def __init__(
        self,
        message: str,
        code: str = "REPORTING_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        merged_details = details or {}
        merged_details["error_code"] = code
        super().__init__(message, merged_details)
        self.code = code


# ---------------------------------------------------------------------------
# Phase 6.5 — API Security, Authentication & Request Protection Errors
# ---------------------------------------------------------------------------


class APIAuthenticationError(ResearchMindError):
    """Raised when an API request lacks valid credentials or presents an invalid API key."""

    def __init__(
        self,
        reason: str = "Invalid or missing API key",
        details: dict[str, Any] | None = None,
    ) -> None:
        merged_details = details or {}
        merged_details["error_code"] = "UNAUTHORIZED"
        super().__init__(reason, merged_details)
        self.code = "UNAUTHORIZED"


class RateLimitExceededError(ResearchMindError):
    """Raised when a client exceeds the configured request rate limit threshold."""

    def __init__(
        self,
        retry_after_seconds: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged_details = details or {}
        merged_details["error_code"] = "RATE_LIMIT_EXCEEDED"
        merged_details["retry_after_seconds"] = retry_after_seconds
        super().__init__(
            f"Rate limit exceeded. Retry after {retry_after_seconds} seconds.",
            merged_details,
        )
        self.code = "RATE_LIMIT_EXCEEDED"
        self.retry_after_seconds = retry_after_seconds


class RequestPayloadTooLargeError(ResearchMindError):
    """Raised when a request body exceeds the configured maximum byte limit."""

    def __init__(
        self,
        byte_count: int | None = None,
        max_bytes: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged_details = details or {}
        merged_details["error_code"] = "PAYLOAD_TOO_LARGE"
        if byte_count is not None:
            merged_details["byte_count"] = byte_count
        if max_bytes is not None:
            merged_details["max_bytes"] = max_bytes
        super().__init__(
            "Request payload exceeds the maximum allowed size.",
            merged_details,
        )
        self.code = "PAYLOAD_TOO_LARGE"
        self.byte_count = byte_count
        self.max_bytes = max_bytes
