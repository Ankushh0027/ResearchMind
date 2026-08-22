"""Research domain and state models."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.enums import (
    AgentRole,
    EdgeType,
    RunStage,
    TaskStatus,
    TaskType,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ResearchGoal(BaseModel):
    """User-submitted research objective and operational boundaries."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    goal_id: str = Field(..., min_length=1, description="Unique goal identifier")
    query: str = Field(..., min_length=3, description="Main inquiry or research prompt")
    constraints: dict[str, Any] = Field(
        default_factory=dict, description="Execution boundaries (e.g. depth, sources)"
    )
    domain_tags: tuple[str, ...] = Field(
        default_factory=tuple, description="Semantic domains (e.g. tech, biotech)"
    )
    max_subtasks: int = Field(
        default=10, ge=1, le=50, description="Upper bound on decomposed subtasks"
    )
    schema_version: str = Field(default="1.0.0", description="Contract schema version")
    created_at: datetime = Field(default_factory=_utc_now)


class SubtaskNode(BaseModel):
    """Discrete atomic node in the research execution graph."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subtask_id: str = Field(..., min_length=1, description="Unique node identifier")
    task_type: TaskType = Field(..., description="Classification of the task")
    objective: str = Field(..., min_length=1, description="Goal of this subtask")
    search_queries: tuple[str, ...] = Field(
        default_factory=tuple, description="Initial search queries if applicable"
    )
    timeout_seconds: int = Field(
        default=120, ge=5, le=3600, description="Task execution timeout"
    )
    max_retries: int = Field(
        default=3, ge=0, le=10, description="Maximum retry attempts on failure"
    )
    assigned_role: AgentRole = Field(
        default=AgentRole.RESEARCHER,
        description="Agent role responsible for execution",
    )
    input_context: dict[str, Any] = Field(
        default_factory=dict, description="Contextual parameters or dependencies input"
    )


class DependencyEdge(BaseModel):
    """Directed dependency link connecting two subtask nodes (source -> target)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(
        ..., min_length=1, description="Prerequisite node (must complete first)"
    )
    target_id: str = Field(
        ..., min_length=1, description="Dependent node (awaits prerequisite)"
    )
    edge_type: EdgeType = Field(
        default=EdgeType.DATA, description="Dependency relationship type"
    )

    @field_validator("target_id")
    @classmethod
    def prevent_self_dependency(cls, target_id: str, info: Any) -> str:
        source_id = info.data.get("source_id")
        if source_id and source_id == target_id:
            raise ValueError(f"Self-dependency detected on node '{target_id}'")
        return target_id


class PlanMetadata(BaseModel):
    """Metadata detailing the formulation of a research plan."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    created_by_agent: str = Field(
        default="planner", description="Identifier of planning agent"
    )
    total_estimated_depth: int = Field(
        default=1, ge=1, description="Estimated critical path depth"
    )
    notes: str | None = Field(default=None, description="Planning notes or rationale")


class ResearchPlan(BaseModel):
    """Structured, versioned execution plan decomposed by the Planner Agent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    plan_id: str = Field(..., min_length=1, description="Unique plan identifier")
    run_id: str = Field(..., min_length=1, description="Associated research run ID")
    goal: ResearchGoal = Field(..., description="Original research goal")
    nodes: dict[str, SubtaskNode] = Field(
        ..., description="Map of subtask_id to SubtaskNode"
    )
    edges: tuple[DependencyEdge, ...] = Field(
        default_factory=tuple, description="Dependency edges between nodes"
    )
    metadata: PlanMetadata = Field(
        default_factory=PlanMetadata, description="Plan formulation metadata"
    )
    version: int = Field(default=1, ge=1, description="Plan revision version")
    is_validated: bool = Field(
        default=False, description="Whether DAG validation succeeded"
    )
    created_at: datetime = Field(default_factory=_utc_now)


class StageTransitionEvent(BaseModel):
    """Immutable audit record of a research run lifecycle stage transition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(..., min_length=1, description="Unique event identifier")
    run_id: str = Field(..., min_length=1, description="Research run identifier")
    from_stage: RunStage = Field(..., description="Previous stage")
    to_stage: RunStage = Field(..., description="New stage")
    timestamp: datetime = Field(default_factory=_utc_now)
    trigger: str = Field(
        ..., min_length=1, description="Event or reason triggering the transition"
    )
    actor: str = Field(
        default="system", description="Agent or component initiating transition"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional context or diagnostics"
    )


class TaskStateRecord(BaseModel):
    """Persistent execution tracking record for a single subtask."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subtask_id: str = Field(..., min_length=1, description="Subtask identifier")
    run_id: str = Field(..., min_length=1, description="Research run identifier")
    status: TaskStatus = Field(
        default=TaskStatus.PENDING, description="Current execution status"
    )
    attempt_count: int = Field(
        default=0, ge=0, description="Number of execution attempts executed"
    )
    max_attempts: int = Field(
        default=3, ge=1, description="Maximum execution attempts allowed"
    )
    worker_id: str | None = Field(
        default=None, description="Worker identifier currently executing task"
    )
    started_at: datetime | None = Field(
        default=None, description="Start timestamp of latest attempt"
    )
    completed_at: datetime | None = Field(
        default=None, description="Completion timestamp"
    )
    error_message: str | None = Field(
        default=None, description="Sanitized error description on failure"
    )
    idempotency_key: str = Field(
        ..., min_length=1, description="Deterministic idempotency token"
    )


class RunState(BaseModel):
    """Top-level aggregate state for an active or completed research run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(..., min_length=1, description="Unique research run ID")
    goal: ResearchGoal = Field(..., description="Research goal specification")
    current_stage: RunStage = Field(
        default=RunStage.CREATED, description="Active lifecycle stage"
    )
    active_plan: ResearchPlan | None = Field(
        default=None, description="Active validated research plan"
    )
    tasks: dict[str, TaskStateRecord] = Field(
        default_factory=dict, description="Map of subtask_id to TaskStateRecord"
    )
    stage_history: tuple[StageTransitionEvent, ...] = Field(
        default_factory=tuple, description="Chronological list of stage transitions"
    )
    checkpoint_counter: int = Field(
        default=0, ge=0, description="Monotonically increasing checkpoint version"
    )
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    completed_at: datetime | None = Field(
        default=None, description="Timestamp when reached terminal state"
    )
    schema_version: str = Field(
        default="1.0.0", description="State contract schema version"
    )
