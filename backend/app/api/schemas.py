"""Pydantic schemas and contracts for FastAPI REST and SSE endpoints."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.common.enums import RunStage
from app.intelligence.models import ResearchDossier
from app.orchestration.contracts import TokenUsage


def _utc_now() -> datetime:
    return datetime.now(UTC)


class CreateRunRequest(BaseModel):
    """Payload for submitting a new autonomous research run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str = Field(
        ...,
        min_length=3,
        max_length=2000,
        description="The primary research inquiry or topic",
    )
    domain_tags: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Semantic domain tags (e.g. ['biomedical', 'physics'])",
    )
    constraints: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional operational or depth constraints",
    )
    max_subtasks: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Upper bound on decomposed subtasks",
    )


class RunSummaryResponse(BaseModel):
    """Brief summary of a created or active research run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(..., description="Unique research run identifier")
    goal_query: str = Field(..., description="Original inquiry topic")
    status: RunStage = Field(..., description="Current execution stage of the run")
    created_at: datetime = Field(
        default_factory=_utc_now, description="Submission timestamp"
    )
    duration_seconds: float = Field(
        default=0.0, ge=0.0, description="Elapsed execution time"
    )


class RunDetailResponse(BaseModel):
    """Comprehensive status and results for a research run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(..., description="Unique research run identifier")
    plan_id: str | None = Field(default=None, description="Active research plan ID")
    goal_query: str = Field(..., description="Original inquiry topic")
    status: RunStage = Field(..., description="Current execution stage")
    completed_task_ids: tuple[str, ...] = Field(
        default_factory=tuple, description="IDs of completed subtasks"
    )
    failed_task_ids: tuple[str, ...] = Field(
        default_factory=tuple, description="IDs of failed subtasks"
    )
    cancelled_task_ids: tuple[str, ...] = Field(
        default_factory=tuple, description="IDs of cancelled subtasks"
    )
    total_token_usage: TokenUsage = Field(
        default_factory=TokenUsage, description="Aggregated token usage"
    )
    duration_seconds: float = Field(
        default=0.0, ge=0.0, description="Total execution duration in seconds"
    )
    dossier: ResearchDossier | None = Field(
        default=None, description="Final compiled ResearchDossier if completed"
    )
    error: str | None = Field(
        default=None, description="Terminal error message if failed"
    )
    created_at: datetime = Field(
        default_factory=_utc_now, description="Submission timestamp"
    )


class CancelRunResponse(BaseModel):
    """Response returned when a research run cancellation is requested."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(..., description="Target research run ID")
    status: RunStage = Field(..., description="Updated run stage")
    message: str = Field(..., description="Status summary message")


class HealthResponse(BaseModel):
    """System liveness and readiness health payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str = Field(default="ok", description="Service health status")
    version: str = Field(default="0.1.0", description="API version")
    timestamp: datetime = Field(default_factory=_utc_now)


class ErrorResponse(BaseModel):
    """Standardized machine-readable error response."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    error_code: str = Field(..., description="Standardized error code")
    message: str = Field(..., description="Human-readable error description")
    details: dict[str, Any] | None = Field(
        default=None, description="Additional contextual metadata"
    )


__all__ = [
    "CancelRunResponse",
    "CreateRunRequest",
    "ErrorResponse",
    "HealthResponse",
    "RunDetailResponse",
    "RunSummaryResponse",
]
