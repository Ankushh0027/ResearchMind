"""Property-based testing for DAG validation and topological sort using Hypothesis."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.common.enums import TaskType
from app.common.errors import DAGValidationError
from app.state.models import DependencyEdge, ResearchGoal, ResearchPlan, SubtaskNode
from app.tasks.dag import DAGValidator


@st.composite
def random_valid_dag_strategy(draw: st.DrawFn) -> ResearchPlan:
    """Hypothesis strategy generating arbitrary strictly-acyclic DAGs."""
    num_nodes = draw(st.integers(min_value=1, max_value=15))
    node_ids = [f"N{i:02d}" for i in range(num_nodes)]

    nodes = {
        nid: SubtaskNode(
            subtask_id=nid,
            task_type=TaskType.WEB_SEARCH,
            objective=f"Objective for {nid}",
        )
        for nid in node_ids
    }

    # Generate edges strictly where i < j (guarantees acyclicity)
    possible_edges = [
        (node_ids[i], node_ids[j])
        for i in range(num_nodes)
        for j in range(i + 1, num_nodes)
    ]
    selected_edges = draw(
        st.lists(
            st.sampled_from(possible_edges) if possible_edges else st.nothing(),
            unique=True,
            max_size=min(len(possible_edges), 25),
        )
    )

    edge_objs = tuple(
        DependencyEdge(source_id=src, target_id=tgt) for src, tgt in selected_edges
    )

    goal = ResearchGoal(goal_id="g_prop", query="Property test goal")
    return ResearchPlan(
        plan_id="plan_prop",
        run_id="run_prop",
        goal=goal,
        nodes=nodes,
        edges=edge_objs,
    )


@given(plan=random_valid_dag_strategy())
@settings(max_examples=50, deadline=None)
def test_property_acyclic_dag_validates_and_orders_correctly(
    plan: ResearchPlan,
) -> None:
    """Invariant: Every valid DAG validates and preserves topological ordering."""
    validator = DAGValidator(max_nodes=50, max_depth=50, max_fan_out=50)
    result = validator.validate_plan(plan)

    # 1. Output contains all nodes
    assert len(result.topological_order) == len(plan.nodes)
    assert set(result.topological_order) == set(plan.nodes.keys())

    # 2. Invariant: For every edge (u -> v), u must precede v in topological order
    pos_map = {nid: idx for idx, nid in enumerate(result.topological_order)}
    for edge in plan.edges:
        assert pos_map[edge.source_id] < pos_map[edge.target_id]


@given(num_nodes=st.integers(min_value=2, max_value=8))
@settings(max_examples=30, deadline=None)
def test_property_cyclic_graph_always_fails_validation(num_nodes: int) -> None:
    """Invariant: Any graph containing a cycle must raise DAGValidationError with CYCLE_DETECTED."""
    node_ids = [f"node_{i}" for i in range(num_nodes)]
    nodes = {
        nid: SubtaskNode(
            subtask_id=nid,
            task_type=TaskType.WEB_SEARCH,
            objective=f"Task {nid}",
        )
        for nid in node_ids
    }

    # Create cycle: node_0 -> node_1 -> ... -> node_n-1 -> node_0
    edges = [
        DependencyEdge(source_id=node_ids[i], target_id=node_ids[(i + 1) % num_nodes])
        for i in range(num_nodes)
    ]

    goal = ResearchGoal(goal_id="g_cyc", query="Cycle test goal")
    plan = ResearchPlan(
        plan_id="p_cyc",
        run_id="r_cyc",
        goal=goal,
        nodes=nodes,
        edges=tuple(edges),
    )

    validator = DAGValidator(max_nodes=50, max_depth=50, max_fan_out=50)
    with pytest.raises(DAGValidationError) as exc_info:
        validator.validate_plan(plan)
    assert exc_info.value.error_code == "CYCLE_DETECTED"
    assert len(exc_info.value.violating_nodes) > 0
