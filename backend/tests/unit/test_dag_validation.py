"""Unit tests for DAG validation engine and topological sort."""

import pytest

from app.common.enums import TaskType
from app.common.errors import DAGValidationError
from app.state.models import DependencyEdge, ResearchGoal, ResearchPlan, SubtaskNode
from app.tasks.dag import DAGValidator


def _make_node(subtask_id: str, objective: str = "Search") -> SubtaskNode:
    return SubtaskNode(
        subtask_id=subtask_id,
        task_type=TaskType.WEB_SEARCH,
        objective=objective,
    )


def _make_plan(
    nodes: list[SubtaskNode], edges: list[tuple[str, str]] | None = None
) -> ResearchPlan:
    goal = ResearchGoal(goal_id="g1", query="Test research goal")
    node_map = {n.subtask_id: n for n in nodes}
    edge_objs = tuple(
        DependencyEdge(source_id=src, target_id=tgt) for src, tgt in (edges or [])
    )
    return ResearchPlan(
        plan_id="p1",
        run_id="r1",
        goal=goal,
        nodes=node_map,
        edges=edge_objs,
    )


def test_valid_linear_dag() -> None:
    """Verify linear execution pipeline (A -> B -> C)."""
    nodes = [_make_node("A"), _make_node("B"), _make_node("C")]
    plan = _make_plan(nodes, [("A", "B"), ("B", "C")])

    validator = DAGValidator()
    result = validator.validate_plan(plan)

    assert result.topological_order == ("A", "B", "C")
    assert result.metrics.critical_path_depth == 3
    assert result.metrics.root_node_ids == ("A",)
    assert result.metrics.leaf_node_ids == ("C",)


def test_valid_diamond_dag() -> None:
    """Verify diamond topology (A -> B, A -> C, B -> D, C -> D)."""
    nodes = [_make_node("A"), _make_node("B"), _make_node("C"), _make_node("D")]
    plan = _make_plan(nodes, [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")])

    validator = DAGValidator()
    result = validator.validate_plan(plan)

    assert result.topological_order[0] == "A"
    assert result.topological_order[-1] == "D"
    assert set(result.topological_order[1:3]) == {"B", "C"}
    assert result.metrics.critical_path_depth == 3


def test_empty_graph_rejected() -> None:
    """Verify empty nodes map raises DAGValidationError."""
    goal = ResearchGoal(goal_id="g1", query="Empty goal")
    plan = ResearchPlan(plan_id="p1", run_id="r1", goal=goal, nodes={}, edges=())

    validator = DAGValidator()
    with pytest.raises(DAGValidationError) as exc:
        validator.validate_plan(plan)
    assert exc.value.error_code == "EMPTY_GRAPH"


def test_node_key_mismatch_rejected() -> None:
    """Verify mismatch between dict key and subtask_id raises error."""
    goal = ResearchGoal(goal_id="g1", query="Key mismatch")
    node = _make_node("node_a")
    plan = ResearchPlan(
        plan_id="p1",
        run_id="r1",
        goal=goal,
        nodes={"wrong_key": node},
        edges=(),
    )

    validator = DAGValidator()
    with pytest.raises(DAGValidationError) as exc:
        validator.validate_plan(plan)
    assert exc.value.error_code == "NODE_KEY_MISMATCH"


def test_missing_source_node_rejected() -> None:
    """Verify edge with non-existent source node is caught."""
    nodes = [_make_node("A"), _make_node("B")]
    # Bypass model validation using a synthetic plan where source node is missing
    goal = ResearchGoal(goal_id="g1", query="Missing source")
    edge = DependencyEdge(source_id="non_existent", target_id="B")
    plan = ResearchPlan(
        plan_id="p1",
        run_id="r1",
        goal=goal,
        nodes={"A": nodes[0], "B": nodes[1]},
        edges=(edge,),
    )

    validator = DAGValidator()
    with pytest.raises(DAGValidationError) as exc:
        validator.validate_plan(plan)
    assert exc.value.error_code == "MISSING_SOURCE_NODE"


def test_missing_target_node_rejected() -> None:
    """Verify edge with non-existent target node is caught."""
    nodes = [_make_node("A"), _make_node("B")]
    goal = ResearchGoal(goal_id="g1", query="Missing target")
    edge = DependencyEdge(source_id="A", target_id="non_existent")
    plan = ResearchPlan(
        plan_id="p1",
        run_id="r1",
        goal=goal,
        nodes={"A": nodes[0], "B": nodes[1]},
        edges=(edge,),
    )

    validator = DAGValidator()
    with pytest.raises(DAGValidationError) as exc:
        validator.validate_plan(plan)
    assert exc.value.error_code == "MISSING_TARGET_NODE"


def test_two_node_cycle_detected() -> None:
    """Verify cycle (A -> B -> A) is detected."""
    nodes = [_make_node("A"), _make_node("B")]
    plan = _make_plan(nodes, [("A", "B"), ("B", "A")])

    validator = DAGValidator()
    with pytest.raises(DAGValidationError) as exc:
        validator.validate_plan(plan)
    assert exc.value.error_code == "CYCLE_DETECTED"
    assert set(exc.value.violating_nodes) == {"A", "B"}


def test_three_node_cycle_detected() -> None:
    """Verify cycle (A -> B -> C -> A) is detected."""
    nodes = [_make_node("A"), _make_node("B"), _make_node("C")]
    plan = _make_plan(nodes, [("A", "B"), ("B", "C"), ("C", "A")])

    validator = DAGValidator()
    with pytest.raises(DAGValidationError) as exc:
        validator.validate_plan(plan)
    assert exc.value.error_code == "CYCLE_DETECTED"
    assert set(exc.value.violating_nodes) == {"A", "B", "C"}


def test_max_nodes_limit_enforced() -> None:
    """Verify maximum nodes boundary enforcement."""
    nodes = [_make_node(f"node_{i}") for i in range(15)]
    plan = _make_plan(nodes)

    validator = DAGValidator(max_nodes=10)
    with pytest.raises(DAGValidationError) as exc:
        validator.validate_plan(plan)
    assert exc.value.error_code == "MAX_NODES_EXCEEDED"


def test_max_fan_out_limit_enforced() -> None:
    """Verify maximum fan-out boundary enforcement."""
    parent = _make_node("parent")
    children = [_make_node(f"child_{i}") for i in range(6)]
    nodes = [parent, *children]
    edges = [("parent", f"child_{i}") for i in range(6)]
    plan = _make_plan(nodes, edges)

    validator = DAGValidator(max_fan_out=3)
    with pytest.raises(DAGValidationError) as exc:
        validator.validate_plan(plan)
    assert exc.value.error_code == "MAX_FAN_OUT_EXCEEDED"


def test_max_depth_limit_enforced() -> None:
    """Verify maximum depth boundary enforcement."""
    nodes = [_make_node(f"N{i}") for i in range(5)]
    edges = [(f"N{i}", f"N{i + 1}") for i in range(4)]
    plan = _make_plan(nodes, edges)

    validator = DAGValidator(max_depth=3)
    with pytest.raises(DAGValidationError) as exc:
        validator.validate_plan(plan)
    assert exc.value.error_code == "MAX_DEPTH_EXCEEDED"


def test_deterministic_topological_sort() -> None:
    """Verify topological order is completely deterministic and stable across calls."""
    nodes = [_make_node(nid) for nid in ["Z", "M", "A", "B", "C"]]
    # A -> M, B -> M, C -> Z
    plan = _make_plan(nodes, [("A", "M"), ("B", "M"), ("C", "Z")])

    validator = DAGValidator()
    result1 = validator.validate_plan(plan)
    result2 = validator.validate_plan(plan)

    assert result1.topological_order == result2.topological_order
    # Roots "A", "B", "C" should be processed in alphabetical order
    assert result1.topological_order[:3] == ("A", "B", "C")
