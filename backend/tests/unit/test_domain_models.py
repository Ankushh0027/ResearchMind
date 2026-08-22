"""Unit tests for core research domain models."""

import pytest
from pydantic import ValidationError

from app.common.enums import AgentRole, EdgeType, RunStage, TaskStatus, TaskType
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


def test_research_goal_creation_and_immutability() -> None:
    """Verify ResearchGoal instantiation, validation, and frozen immutability."""
    goal = ResearchGoal(
        goal_id="goal_123",
        query="Compare Transformer vs Mamba architecture efficiency",
        domain_tags=("ai", "nlp"),
        constraints={"max_depth": 3},
    )
    assert goal.goal_id == "goal_123"
    assert goal.query.startswith("Compare")
    assert goal.schema_version == "1.0.0"

    # Immutability check
    field_to_mutate = "query"
    with pytest.raises(ValidationError):
        setattr(goal, field_to_mutate, "New query")


def test_research_goal_short_query_validation() -> None:
    """Verify short query raises validation error."""
    with pytest.raises(ValidationError):
        ResearchGoal(goal_id="g1", query="ab")


def test_subtask_node_creation() -> None:
    """Verify SubtaskNode validation and defaults."""
    node = SubtaskNode(
        subtask_id="task_01",
        task_type=TaskType.WEB_SEARCH,
        objective="Search Mamba benchmark benchmarks",
        search_queries=("mamba state space model benchmark",),
        assigned_role=AgentRole.RESEARCHER,
    )
    assert node.subtask_id == "task_01"
    assert node.timeout_seconds == 120
    assert node.max_retries == 3
    assert node.assigned_role == AgentRole.RESEARCHER


def test_dependency_edge_creation() -> None:
    """Verify valid DependencyEdge creation."""
    edge = DependencyEdge(
        source_id="task_01",
        target_id="task_02",
        edge_type=EdgeType.DATA,
    )
    assert edge.source_id == "task_01"
    assert edge.target_id == "task_02"
    assert edge.edge_type == EdgeType.DATA


def test_dependency_edge_self_dependency_rejected() -> None:
    """Verify that a node depending on itself fails validation."""
    with pytest.raises(ValidationError, match="Self-dependency detected"):
        DependencyEdge(source_id="task_01", target_id="task_01")


def test_research_plan_serialization() -> None:
    """Verify JSON serialization and round-trip deserialization of ResearchPlan."""
    goal = ResearchGoal(goal_id="g1", query="Analyze AI scaling laws")
    node1 = SubtaskNode(
        subtask_id="t1",
        task_type=TaskType.WEB_SEARCH,
        objective="Gather compute scaling curves",
    )
    node2 = SubtaskNode(
        subtask_id="t2",
        task_type=TaskType.SYNTHESIS,
        objective="Synthesize power-law exponents",
        assigned_role=AgentRole.ANALYST,
    )
    edge = DependencyEdge(source_id="t1", target_id="t2")

    plan = ResearchPlan(
        plan_id="p1",
        run_id="run_100",
        goal=goal,
        nodes={"t1": node1, "t2": node2},
        edges=(edge,),
        metadata=PlanMetadata(created_by_agent="planner", total_estimated_depth=2),
    )

    plan_json = plan.model_dump_json()
    assert "Analyze AI scaling laws" in plan_json

    restored_plan = ResearchPlan.model_validate_json(plan_json)
    assert restored_plan.plan_id == plan.plan_id
    assert len(restored_plan.nodes) == 2
    assert restored_plan.edges[0].source_id == "t1"


def test_run_state_lifecycle_structure() -> None:
    """Verify RunState aggregates plan, tasks, and stage history."""
    goal = ResearchGoal(goal_id="g1", query="Investigate quantum algorithms")
    run_state = RunState(
        run_id="run_200",
        goal=goal,
        current_stage=RunStage.CREATED,
    )
    assert run_state.run_id == "run_200"
    assert run_state.current_stage == RunStage.CREATED
    assert len(run_state.tasks) == 0
    assert len(run_state.stage_history) == 0


def test_stage_transition_event_creation() -> None:
    """Verify StageTransitionEvent audit recording."""
    event = StageTransitionEvent(
        event_id="evt_01",
        run_id="run_200",
        from_stage=RunStage.CREATED,
        to_stage=RunStage.QUEUED,
        trigger="task_published",
        actor="api_gateway",
    )
    assert event.from_stage == RunStage.CREATED
    assert event.to_stage == RunStage.QUEUED
    assert event.actor == "api_gateway"


def test_task_state_record_creation() -> None:
    """Verify TaskStateRecord initialization."""
    record = TaskStateRecord(
        subtask_id="t1",
        run_id="run_200",
        status=TaskStatus.SCHEDULED,
        attempt_count=1,
        idempotency_key="idem_key_123",
    )
    assert record.subtask_id == "t1"
    assert record.status == TaskStatus.SCHEDULED
    assert record.attempt_count == 1
