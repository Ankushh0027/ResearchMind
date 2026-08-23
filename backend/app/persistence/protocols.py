"""Durable state models and repository protocol abstractions for ResearchMind."""

import time
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from app.common.enums import RunStage
from app.intelligence.models import ResearchDossier
from app.orchestration.cancellation import CancellationToken
from app.orchestration.contracts import TokenUsage
from app.orchestration.events import ExecutionEvent
from app.orchestration.protocols import CheckpointRepositoryProtocol
from app.orchestration.runtime import InMemoryEventSink
from app.state.models import ResearchGoal
from app.state.snapshot import CheckpointSnapshot


def _utc_now() -> datetime:
    return datetime.now(UTC)


class RunContext:
    """Runtime execution container for an active or completed research run."""

    def __init__(
        self,
        run_id: str,
        goal: ResearchGoal,
        cancellation_token: CancellationToken,
        event_sink: InMemoryEventSink,
        checkpoint_repo: CheckpointRepositoryProtocol,
    ) -> None:
        self.run_id = run_id
        self.goal = goal
        self.cancellation_token = cancellation_token
        self.event_sink = event_sink
        self.checkpoint_repo = checkpoint_repo
        self.created_at: datetime = _utc_now()
        self.start_time: float = time.monotonic()
        self.status: RunStage = RunStage.QUEUED
        self.plan_id: str | None = None
        self.completed_task_ids: list[str] = []
        self.failed_task_ids: list[str] = []
        self.cancelled_task_ids: list[str] = []
        self.total_token_usage: TokenUsage = TokenUsage()
        self.duration_seconds: float = 0.0
        self.dossier: ResearchDossier | None = None
        self.error: str | None = None


class RunRecord(BaseModel):
    """Durable persistent record representing a research inquiry run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(..., min_length=1, description="Unique research run identifier")
    goal: ResearchGoal = Field(..., description="Original research inquiry objective")
    status: RunStage = Field(
        default=RunStage.QUEUED, description="Current lifecycle stage"
    )
    plan_id: str | None = Field(default=None, description="Decomposed research plan ID")
    completed_task_ids: tuple[str, ...] = Field(
        default_factory=tuple, description="IDs of successfully completed subtasks"
    )
    failed_task_ids: tuple[str, ...] = Field(
        default_factory=tuple, description="IDs of failed subtasks"
    )
    cancelled_task_ids: tuple[str, ...] = Field(
        default_factory=tuple, description="IDs of cancelled subtasks"
    )
    total_token_usage: TokenUsage = Field(
        default_factory=TokenUsage, description="Aggregated LLM token usage"
    )
    duration_seconds: float = Field(
        default=0.0, ge=0.0, description="Total execution duration in seconds"
    )
    dossier: ResearchDossier | None = Field(
        default=None, description="Final compiled ResearchDossier deliverable"
    )
    error: str | None = Field(
        default=None, description="Terminal error message if execution failed"
    )
    is_cancelled: bool = Field(
        default=False, description="Whether cancellation was requested for this run"
    )
    cancellation_reason: str | None = Field(
        default=None, description="Reason recorded when cancellation was requested"
    )
    version: int = Field(
        default=1, ge=1, description="Optimistic locking sequence version"
    )
    created_at: datetime = Field(
        default_factory=_utc_now, description="Run creation timestamp"
    )
    updated_at: datetime = Field(
        default_factory=_utc_now, description="Last update timestamp"
    )

    def with_updates(
        self,
        *,
        status: RunStage | None = None,
        plan_id: str | None = None,
        completed_task_ids: tuple[str, ...] | list[str] | None = None,
        failed_task_ids: tuple[str, ...] | list[str] | None = None,
        cancelled_task_ids: tuple[str, ...] | list[str] | None = None,
        total_token_usage: TokenUsage | None = None,
        duration_seconds: float | None = None,
        dossier: ResearchDossier | None = None,
        error: str | None = None,
        is_cancelled: bool | None = None,
        cancellation_reason: str | None = None,
        increment_version: bool = True,
    ) -> "RunRecord":
        """Produce an updated immutable copy of this RunRecord with incremented version."""
        dump = self.model_dump()
        if status is not None:
            dump["status"] = status
        if plan_id is not None:
            dump["plan_id"] = plan_id
        if completed_task_ids is not None:
            dump["completed_task_ids"] = tuple(completed_task_ids)
        if failed_task_ids is not None:
            dump["failed_task_ids"] = tuple(failed_task_ids)
        if cancelled_task_ids is not None:
            dump["cancelled_task_ids"] = tuple(cancelled_task_ids)
        if total_token_usage is not None:
            dump["total_token_usage"] = total_token_usage.model_dump()
        if duration_seconds is not None:
            dump["duration_seconds"] = duration_seconds
        if dossier is not None:
            dump["dossier"] = dossier.model_dump()
        if error is not None:
            dump["error"] = error
        if is_cancelled is not None:
            dump["is_cancelled"] = is_cancelled
        if cancellation_reason is not None:
            dump["cancellation_reason"] = cancellation_reason
        if increment_version:
            dump["version"] = self.version + 1
        dump["updated_at"] = _utc_now()
        return RunRecord.model_validate(dump)


@runtime_checkable
class RunRepositoryProtocol(Protocol):
    """Protocol for durable storage and retrieval of research run records."""

    async def create_run(self, record: RunRecord) -> RunRecord:
        """Persist a new research run record. Raises error if run_id already exists."""
        ...

    async def get_run(self, run_id: str) -> RunRecord | None:
        """Fetch a research run record by its unique identifier."""
        ...

    async def update_run(
        self, record: RunRecord, expected_version: int | None = None
    ) -> RunRecord:
        """Update an existing run record with optimistic concurrency validation."""
        ...

    async def list_runs(self, limit: int = 50, offset: int = 0) -> list[RunRecord]:
        """List stored research runs in reverse chronological order."""
        ...


@runtime_checkable
class EventRepositoryProtocol(Protocol):
    """Protocol for persisting and streaming research execution events."""

    async def emit_event(self, event: ExecutionEvent) -> None:
        """Persist an execution event."""
        ...

    async def get_events(
        self, run_id: str, after_index: int = 0
    ) -> list[ExecutionEvent]:
        """Fetch chronological execution events for a given run ID."""
        ...


__all__ = [
    "CheckpointRepositoryProtocol",
    "CheckpointSnapshot",
    "EventRepositoryProtocol",
    "RunContext",
    "RunRecord",
    "RunRepositoryProtocol",
]
