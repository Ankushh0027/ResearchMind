"""State models, lifecycle transitions, and checkpoint persistence contracts."""

from app.state.models import (
    DependencyEdge,
    PlanMetadata,
    ResearchGoal,
    ResearchPlan,
    RunState,
    StageTransitionEvent,
    SubtaskNode,
    TaskStateRecord,
)
from app.state.snapshot import (
    CheckpointSnapshot,
    compute_state_hash,
    create_checkpoint,
)
from app.state.transitions import (
    ALLOWED_RUN_STAGE_TRANSITIONS,
    ALLOWED_TASK_STATUS_TRANSITIONS,
    can_transition_run_stage,
    can_transition_task_status,
    is_terminal_run_stage,
    is_terminal_task_status,
    transition_run_stage,
    validate_task_transition,
)

__all__ = [
    "ALLOWED_RUN_STAGE_TRANSITIONS",
    "ALLOWED_TASK_STATUS_TRANSITIONS",
    "CheckpointSnapshot",
    "DependencyEdge",
    "PlanMetadata",
    "ResearchGoal",
    "ResearchPlan",
    "RunState",
    "StageTransitionEvent",
    "SubtaskNode",
    "TaskStateRecord",
    "can_transition_run_stage",
    "can_transition_task_status",
    "compute_state_hash",
    "create_checkpoint",
    "is_terminal_run_stage",
    "is_terminal_task_status",
    "transition_run_stage",
    "validate_task_transition",
]
