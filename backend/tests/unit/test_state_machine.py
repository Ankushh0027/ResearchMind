"""Unit tests for the research lifecycle state machine, transitions, and checkpoints."""

import pytest

from app.common.enums import RunStage, TaskStatus
from app.common.errors import CheckpointCorruptedError, InvalidStateTransitionError
from app.state.models import ResearchGoal, RunState
from app.state.snapshot import (
    create_checkpoint,
)
from app.state.transitions import (
    can_transition_run_stage,
    can_transition_task_status,
    is_terminal_run_stage,
    transition_run_stage,
    validate_task_transition,
)


def test_valid_standard_run_lifecycle_transitions() -> None:
    """Verify standard happy-path progression through all pipeline stages."""
    stages = [
        RunStage.CREATED,
        RunStage.QUEUED,
        RunStage.RUNNING,
        RunStage.PLANNING,
        RunStage.RESEARCHING,
        RunStage.ANALYZING,
        RunStage.VERIFYING,
        RunStage.EVALUATING,
        RunStage.REPORTING,
        RunStage.COMPLETED,
    ]

    for i in range(len(stages) - 1):
        curr = stages[i]
        nxt = stages[i + 1]
        assert can_transition_run_stage(curr, nxt) is True
        event = transition_run_stage(
            run_id="run_100",
            current_stage=curr,
            target_stage=nxt,
            trigger=f"advance_to_{nxt}",
        )
        assert event.from_stage == curr
        assert event.to_stage == nxt


def test_invalid_run_stage_transitions() -> None:
    """Verify illegal transitions are rejected with InvalidStateTransitionError."""
    illegal_pairs = [
        (RunStage.CREATED, RunStage.COMPLETED),
        (RunStage.PLANNING, RunStage.REPORTING),
        (RunStage.REPORTING, RunStage.CREATED),
        (RunStage.QUEUED, RunStage.ANALYZING),
    ]

    for curr, nxt in illegal_pairs:
        assert can_transition_run_stage(curr, nxt) is False
        with pytest.raises(InvalidStateTransitionError):
            transition_run_stage(
                run_id="run_100",
                current_stage=curr,
                target_stage=nxt,
                trigger="illegal_jump",
            )


def test_terminal_states_prevent_further_transitions() -> None:
    """Verify terminal stages have zero allowed outbound transitions."""
    terminals = [RunStage.COMPLETED, RunStage.FAILED, RunStage.CANCELLED]
    for term in terminals:
        assert is_terminal_run_stage(term) is True
        for any_stage in RunStage:
            assert can_transition_run_stage(term, any_stage) is False
            with pytest.raises(InvalidStateTransitionError):
                transition_run_stage(
                    run_id="run_100",
                    current_stage=term,
                    target_stage=any_stage,
                    trigger="resurrect",
                )


def test_research_loop_and_retry_transitions() -> None:
    """Verify valid loop-back transitions for re-research and retrying."""
    # Re-research triggered from Analysis or Verification
    assert can_transition_run_stage(RunStage.ANALYZING, RunStage.RESEARCHING) is True
    assert can_transition_run_stage(RunStage.VERIFYING, RunStage.RESEARCHING) is True
    assert can_transition_run_stage(RunStage.EVALUATING, RunStage.RESEARCHING) is True

    # Retry transition
    assert can_transition_run_stage(RunStage.RESEARCHING, RunStage.RETRYING) is True
    assert can_transition_run_stage(RunStage.RETRYING, RunStage.RESEARCHING) is True


def test_task_status_transitions() -> None:
    """Verify task status transition logic."""
    validate_task_transition("t1", TaskStatus.PENDING, TaskStatus.SCHEDULED)
    validate_task_transition("t1", TaskStatus.SCHEDULED, TaskStatus.IN_PROGRESS)
    validate_task_transition("t1", TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED)
    validate_task_transition("t1", TaskStatus.FAILED, TaskStatus.SCHEDULED)  # Retry

    # Illegal task transition: COMPLETED -> IN_PROGRESS
    assert (
        can_transition_task_status(TaskStatus.COMPLETED, TaskStatus.IN_PROGRESS)
        is False
    )
    with pytest.raises(InvalidStateTransitionError):
        validate_task_transition("t1", TaskStatus.COMPLETED, TaskStatus.IN_PROGRESS)


def test_checkpoint_snapshot_creation_and_hash_integrity() -> None:
    """Verify checkpoint creation, state serialization, and tamper detection."""
    goal = ResearchGoal(goal_id="g1", query="State checkpoint test")
    run_state = RunState(
        run_id="run_chk_01",
        goal=goal,
        current_stage=RunStage.RESEARCHING,
        checkpoint_counter=2,
    )

    snapshot = create_checkpoint(run_state)
    assert snapshot.run_id == "run_chk_01"
    assert snapshot.checkpoint_version == 3
    assert snapshot.stage == RunStage.RESEARCHING
    assert snapshot.verify_integrity() is True
    snapshot.assert_valid()


def test_checkpoint_tamper_detection() -> None:
    """Verify that tampering with payload causes CheckpointCorruptedError."""
    goal = ResearchGoal(goal_id="g1", query="Tamper test")
    run_state = RunState(
        run_id="run_tamper",
        goal=goal,
        current_stage=RunStage.PLANNING,
    )
    snapshot = create_checkpoint(run_state)

    # Simulate tampered payload
    tampered_payload = dict(snapshot.state_payload)
    tampered_payload["current_stage"] = "COMPLETED"

    # Create mutated snapshot with original hash
    tampered_snapshot = snapshot.model_copy(update={"state_payload": tampered_payload})
    assert tampered_snapshot.verify_integrity() is False

    with pytest.raises(CheckpointCorruptedError):
        tampered_snapshot.assert_valid()
