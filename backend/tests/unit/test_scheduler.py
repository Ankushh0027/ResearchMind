"""Unit tests for DAGScheduler dependency-aware scheduling and task transitions."""

import pytest

from app.common.enums import AgentRole, TaskType
from app.common.errors import SchedulerError
from app.orchestration.scheduler import DAGScheduler
from app.state.models import DependencyEdge, ResearchGoal, ResearchPlan, SubtaskNode


def _make_node(subtask_id: str) -> SubtaskNode:
    return SubtaskNode(
        subtask_id=subtask_id,
        task_type=TaskType.WEB_SEARCH,
        objective=f"Objective for {subtask_id}",
        assigned_role=AgentRole.RESEARCHER,
    )


def _make_plan(
    nodes: list[SubtaskNode], edges: list[tuple[str, str]] | None = None
) -> ResearchPlan:
    goal = ResearchGoal(goal_id="g1", query="Test goal")
    node_map = {n.subtask_id: n for n in nodes}
    edge_objs = tuple(
        DependencyEdge(source_id=src, target_id=tgt) for src, tgt in (edges or [])
    )
    return ResearchPlan(
        plan_id="p1",
        run_id="run_sched_01",
        goal=goal,
        nodes=node_map,
        edges=edge_objs,
    )


def test_single_task_scheduler() -> None:
    """Verify single task scheduling lifecycle."""
    node = _make_node("T1")
    plan = _make_plan([node])
    scheduler = DAGScheduler(plan)

    runnable = scheduler.get_runnable_tasks()
    assert len(runnable) == 1
    assert runnable[0].subtask_id == "T1"

    scheduler.mark_scheduled("T1")
    scheduler.mark_started("T1", worker_id="w1", attempt=1)
    assert scheduler.get_active_count() == 1
    assert scheduler.is_all_completed() is False

    scheduler.mark_completed("T1")
    assert scheduler.is_all_completed() is True
    assert scheduler.get_active_count() == 0


def test_linear_dag_dependency_blocking() -> None:
    """Verify linear DAG (A -> B -> C): B and C are blocked until prerequisite completes."""
    nodes = [_make_node("A"), _make_node("B"), _make_node("C")]
    plan = _make_plan(nodes, [("A", "B"), ("B", "C")])
    scheduler = DAGScheduler(plan)

    # Initial state: only A is runnable
    runnable = scheduler.get_runnable_tasks()
    assert [n.subtask_id for n in runnable] == ["A"]

    scheduler.mark_scheduled("A")
    scheduler.mark_started("A", "w1", 1)
    assert len(scheduler.get_runnable_tasks()) == 0

    # Completing A unlocks B
    scheduler.mark_completed("A")
    runnable = scheduler.get_runnable_tasks()
    assert [n.subtask_id for n in runnable] == ["B"]

    scheduler.mark_scheduled("B")
    scheduler.mark_started("B", "w1", 1)
    scheduler.mark_completed("B")

    # Completing B unlocks C
    runnable = scheduler.get_runnable_tasks()
    assert [n.subtask_id for n in runnable] == ["C"]

    scheduler.mark_scheduled("C")
    scheduler.mark_started("C", "w1", 1)
    scheduler.mark_completed("C")

    assert scheduler.is_all_completed() is True


def test_diamond_merging_dag_dependency() -> None:
    """Verify diamond DAG (A -> B, A -> C, B -> D, C -> D): D blocked until BOTH B and C finish."""
    nodes = [_make_node("A"), _make_node("B"), _make_node("C"), _make_node("D")]
    plan = _make_plan(nodes, [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")])
    scheduler = DAGScheduler(plan)

    # 1. Start A
    assert [n.subtask_id for n in scheduler.get_runnable_tasks()] == ["A"]
    scheduler.mark_scheduled("A")
    scheduler.mark_started("A", "w1", 1)
    scheduler.mark_completed("A")

    # 2. Both B and C become runnable
    runnable = scheduler.get_runnable_tasks()
    assert [n.subtask_id for n in runnable] == ["B", "C"]

    # Start and complete B
    scheduler.mark_scheduled("B")
    scheduler.mark_started("B", "w1", 1)
    scheduler.mark_completed("B")

    # D is still NOT runnable because C is pending
    runnable = scheduler.get_runnable_tasks()
    assert [n.subtask_id for n in runnable] == ["C"]

    # Start and complete C
    scheduler.mark_scheduled("C")
    scheduler.mark_started("C", "w1", 1)
    scheduler.mark_completed("C")

    # Now D is unlocked
    runnable = scheduler.get_runnable_tasks()
    assert [n.subtask_id for n in runnable] == ["D"]


def test_deterministic_alphabetical_runnable_ordering() -> None:
    """Verify runnable tasks are deterministically sorted alphabetically by subtask_id."""
    nodes = [_make_node("Z"), _make_node("M"), _make_node("A"), _make_node("B")]
    plan = _make_plan(nodes)
    scheduler = DAGScheduler(plan)

    runnable = scheduler.get_runnable_tasks()
    assert [n.subtask_id for n in runnable] == ["A", "B", "M", "Z"]


def test_unknown_task_error() -> None:
    """Verify modifying non-existent task raises SchedulerError."""
    plan = _make_plan([_make_node("T1")])
    scheduler = DAGScheduler(plan)

    with pytest.raises(SchedulerError):
        scheduler.mark_scheduled("NON_EXISTENT")
