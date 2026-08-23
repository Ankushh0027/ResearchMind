"""Typed contracts, models, and protocols for asynchronous research jobs."""

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    return datetime.now(UTC)


class JobStatus(StrEnum):
    """Execution lifecycle status for asynchronous jobs."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    DEAD_LETTERED = "DEAD_LETTERED"


class JobEnvelope(BaseModel):
    """Durable execution envelope wrapping a research job request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: str = Field(..., description="Unique job identifier")
    run_id: str = Field(..., description="Associated research run ID")
    goal_query: str = Field(..., min_length=3, description="Research inquiry topic")
    domain_tags: tuple[str, ...] = Field(
        default_factory=tuple, description="Optional domain tags"
    )
    constraints: dict[str, Any] = Field(
        default_factory=dict, description="Execution constraints"
    )
    max_subtasks: int = Field(
        default=10, ge=1, le=50, description="Max allowed subtasks"
    )
    attempt: int = Field(default=1, ge=1, description="Current execution attempt")
    max_attempts: int = Field(
        default=3, ge=1, le=10, description="Max allowed execution attempts"
    )
    status: JobStatus = Field(
        default=JobStatus.QUEUED, description="Current job status"
    )
    created_at: datetime = Field(
        default_factory=_utc_now, description="Job creation timestamp"
    )
    started_at: datetime | None = Field(
        default=None, description="Job processing start timestamp"
    )
    completed_at: datetime | None = Field(
        default=None, description="Job completion or terminal failure timestamp"
    )
    error: str | None = Field(
        default=None, description="Error message if failed or dead-lettered"
    )
    is_retryable: bool = Field(
        default=True, description="Whether the last failure is retryable"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Custom contextual metadata"
    )

    def with_status(
        self,
        status: JobStatus,
        *,
        error: str | None = None,
        is_retryable: bool | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        attempt: int | None = None,
    ) -> "JobEnvelope":
        """Produce an updated copy of this envelope with modified lifecycle state."""
        updates: dict[str, Any] = {"status": status}
        if error is not None:
            updates["error"] = error
        if is_retryable is not None:
            updates["is_retryable"] = is_retryable
        if started_at is not None:
            updates["started_at"] = started_at
        if completed_at is not None:
            updates["completed_at"] = completed_at
        if attempt is not None:
            updates["attempt"] = attempt

        dump = self.model_dump()
        dump.update(updates)
        if dump.get("created_at") is None:
            dump["created_at"] = _utc_now()
        return JobEnvelope.model_validate(dump)


@runtime_checkable
class JobPublisherProtocol(Protocol):
    """Protocol for publishing research job envelopes to a queue or topic."""

    async def publish(self, envelope: JobEnvelope) -> str:
        """Publish a job envelope to the queue and return the published job_id."""
        ...


@runtime_checkable
class JobHandlerProtocol(Protocol):
    """Protocol representing the worker logic that executes a single job envelope."""

    async def handle_job(self, envelope: JobEnvelope) -> JobEnvelope:
        """Execute the job lifecycle and return the updated envelope."""
        ...


@runtime_checkable
class JobConsumerProtocol(Protocol):
    """Protocol for a background consumer service reading and dispatching jobs."""

    async def start(self) -> None:
        """Start the background consumer loop."""
        ...

    async def stop(self) -> None:
        """Gracefully stop the background consumer loop."""
        ...

    def is_running(self) -> bool:
        """Return whether the consumer is currently active."""
        ...


RunContextResolver = Callable[[str], Any]

__all__ = [
    "JobConsumerProtocol",
    "JobEnvelope",
    "JobHandlerProtocol",
    "JobPublisherProtocol",
    "JobStatus",
    "RunContextResolver",
]
