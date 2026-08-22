"""Finite State Machine (FSM) transitions, transition guards, and lifecycle enforcement."""

import uuid

from app.common.enums import RunStage, TaskStatus
from app.common.errors import InvalidStateTransitionError
from app.state.models import StageTransitionEvent

# Run Stage Allowed Transitions Table
ALLOWED_RUN_STAGE_TRANSITIONS: dict[RunStage, frozenset[RunStage]] = {
    RunStage.CREATED: frozenset({RunStage.QUEUED, RunStage.FAILED, RunStage.CANCELLED}),
    RunStage.QUEUED: frozenset({RunStage.RUNNING, RunStage.FAILED, RunStage.CANCELLED}),
    RunStage.RUNNING: frozenset(
        {RunStage.PLANNING, RunStage.FAILED, RunStage.CANCELLED}
    ),
    RunStage.PLANNING: frozenset(
        {RunStage.RESEARCHING, RunStage.FAILED, RunStage.CANCELLED}
    ),
    RunStage.RESEARCHING: frozenset(
        {RunStage.ANALYZING, RunStage.RETRYING, RunStage.FAILED, RunStage.CANCELLED}
    ),
    RunStage.ANALYZING: frozenset(
        {
            RunStage.VERIFYING,
            RunStage.RESEARCHING,
            RunStage.RETRYING,
            RunStage.FAILED,
            RunStage.CANCELLED,
        }
    ),
    RunStage.VERIFYING: frozenset(
        {
            RunStage.EVALUATING,
            RunStage.RESEARCHING,
            RunStage.RETRYING,
            RunStage.FAILED,
            RunStage.CANCELLED,
        }
    ),
    RunStage.EVALUATING: frozenset(
        {
            RunStage.REPORTING,
            RunStage.RESEARCHING,
            RunStage.RETRYING,
            RunStage.FAILED,
            RunStage.CANCELLED,
        }
    ),
    RunStage.REPORTING: frozenset(
        {RunStage.COMPLETED, RunStage.RETRYING, RunStage.FAILED, RunStage.CANCELLED}
    ),
    RunStage.RETRYING: frozenset(
        {RunStage.RUNNING, RunStage.RESEARCHING, RunStage.FAILED, RunStage.CANCELLED}
    ),
    # Terminal states have no outbound transitions
    RunStage.COMPLETED: frozenset(),
    RunStage.FAILED: frozenset(),
    RunStage.CANCELLED: frozenset(),
}

# Task Status Allowed Transitions Table
ALLOWED_TASK_STATUS_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset(
        {TaskStatus.SCHEDULED, TaskStatus.SKIPPED, TaskStatus.CANCELLED}
    ),
    TaskStatus.SCHEDULED: frozenset(
        {TaskStatus.IN_PROGRESS, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.IN_PROGRESS: frozenset(
        {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.FAILED: frozenset(
        {TaskStatus.SCHEDULED}
    ),  # Allowed when a retry is dispatched
    # Terminal statuses
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
    TaskStatus.SKIPPED: frozenset(),
}

TERMINAL_RUN_STAGES: frozenset[RunStage] = frozenset(
    {RunStage.COMPLETED, RunStage.FAILED, RunStage.CANCELLED}
)

TERMINAL_TASK_STATUSES: frozenset[TaskStatus] = frozenset(
    {TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.SKIPPED}
)


def is_terminal_run_stage(stage: RunStage) -> bool:
    """Check if the given RunStage is terminal (no further transitions allowed)."""
    return stage in TERMINAL_RUN_STAGES


def is_terminal_task_status(status: TaskStatus) -> bool:
    """Check if the given TaskStatus is terminal."""
    return status in TERMINAL_TASK_STATUSES


def can_transition_run_stage(current: RunStage, target: RunStage) -> bool:
    """Evaluate whether a run stage transition is legally allowed."""
    allowed = ALLOWED_RUN_STAGE_TRANSITIONS.get(current, frozenset())
    return target in allowed


def can_transition_task_status(current: TaskStatus, target: TaskStatus) -> bool:
    """Evaluate whether a task status transition is legally allowed."""
    allowed = ALLOWED_TASK_STATUS_TRANSITIONS.get(current, frozenset())
    return target in allowed


def transition_run_stage(
    run_id: str,
    current_stage: RunStage,
    target_stage: RunStage,
    trigger: str,
    actor: str = "system",
    metadata: dict[str, object] | None = None,
) -> StageTransitionEvent:
    """Validate and generate a stage transition event. Raises InvalidStateTransitionError if illegal."""
    if not can_transition_run_stage(current_stage, target_stage):
        reason = (
            "Cannot transition from terminal stage"
            if is_terminal_run_stage(current_stage)
            else f"Transition from '{current_stage}' to '{target_stage}' is not permitted"
        )
        raise InvalidStateTransitionError(
            from_state=str(current_stage),
            to_state=str(target_stage),
            entity_id=run_id,
            reason=reason,
        )

    return StageTransitionEvent(
        event_id=f"evt_{uuid.uuid4().hex[:12]}",
        run_id=run_id,
        from_stage=current_stage,
        to_stage=target_stage,
        trigger=trigger,
        actor=actor,
        metadata=metadata or {},
    )


def validate_task_transition(
    subtask_id: str,
    current_status: TaskStatus,
    target_status: TaskStatus,
) -> None:
    """Validate a task node status transition. Raises InvalidStateTransitionError if illegal."""
    if not can_transition_task_status(current_status, target_status):
        reason = (
            "Cannot transition from terminal task status"
            if is_terminal_task_status(current_status)
            and current_status != TaskStatus.FAILED
            else f"Transition from '{current_status}' to '{target_status}' is not permitted"
        )
        raise InvalidStateTransitionError(
            from_state=str(current_status),
            to_state=str(target_status),
            entity_id=subtask_id,
            reason=reason,
        )
