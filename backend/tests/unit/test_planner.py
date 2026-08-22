"""Comprehensive unit tests for PlannerAgent and goal decomposition engine."""

import pytest
from pydantic import ValidationError

from app.adapters.llm.mock_llm import MockLLMClient
from app.common.enums import AgentRole, RunStage, TaskType
from app.common.errors import DAGValidationError
from app.intelligence.planner import (
    PlannedDecomposition,
    PlannedSubtask,
    PlannerAgent,
    PlannerError,
)
from app.orchestration.executor import DAGExecutor
from app.state.models import ResearchGoal
from app.tasks.dag import DAGValidator


def _make_goal(
    goal_id: str = "g1",
    query: str = "Quantum computing impact on post-quantum cryptography",
    domain_tags: tuple[str, ...] = ("quantum", "cryptography"),
    max_subtasks: int = 10,
) -> ResearchGoal:
    return ResearchGoal(
        goal_id=goal_id,
        query=query,
        domain_tags=domain_tags,
        max_subtasks=max_subtasks,
    )


@pytest.mark.asyncio
async def test_a_simple_single_domain_goal() -> None:
    """Test A: Simple single-domain research goal decomposition."""
    llm = MockLLMClient()
    planner = PlannerAgent(llm_client=llm)

    decomp = PlannedDecomposition(
        rationale="Single subtask web search.",
        subtasks=(
            PlannedSubtask(
                subtask_id="t1",
                task_type=TaskType.WEB_SEARCH,
                objective="Search for recent PQC NIST standards.",
                assigned_role=AgentRole.RESEARCHER,
                search_queries=("NIST PQC standards 2026",),
            ),
        ),
    )
    llm.set_structured_response(PlannedDecomposition, decomp)

    goal = _make_goal(domain_tags=("cryptography",))
    plan = await planner.plan(goal, run_id="run_1", plan_id="plan_1")

    assert plan.plan_id == "plan_1"
    assert plan.run_id == "run_1"
    assert plan.is_validated is True
    assert len(plan.nodes) == 1
    assert "t1" in plan.nodes
    assert plan.nodes["t1"].objective == "Search for recent PQC NIST standards."
    assert len(plan.edges) == 0


@pytest.mark.asyncio
async def test_b_multi_domain_research_goal() -> None:
    """Test B: Multi-domain research goal decomposition across biology and machine learning."""
    llm = MockLLMClient()
    planner = PlannerAgent(llm_client=llm)

    decomp = PlannedDecomposition(
        rationale="Cross-domain investigation.",
        subtasks=(
            PlannedSubtask(
                subtask_id="bio_1",
                task_type=TaskType.ACADEMIC_SEARCH,
                objective="Retrieve protein structure prediction benchmarks.",
                assigned_role=AgentRole.RESEARCHER,
            ),
            PlannedSubtask(
                subtask_id="ml_1",
                task_type=TaskType.ACADEMIC_SEARCH,
                objective="Analyze transformer architectures for folding.",
                assigned_role=AgentRole.RESEARCHER,
            ),
            PlannedSubtask(
                subtask_id="synth_1",
                task_type=TaskType.SYNTHESIS,
                objective="Synthesize structural ML breakthroughs.",
                assigned_role=AgentRole.ANALYST,
                prerequisite_ids=("bio_1", "ml_1"),
            ),
        ),
    )
    llm.set_structured_response(PlannedDecomposition, decomp)

    goal = _make_goal(
        query="AlphaFold and ESMFold architectural comparative analysis",
        domain_tags=("biology", "machine_learning"),
    )
    plan, validated_dag = await planner.plan_and_validate(goal)

    assert plan.is_validated is True
    assert len(plan.nodes) == 3
    assert len(plan.edges) == 2
    assert validated_dag.metrics.critical_path_depth == 2
    assert validated_dag.metrics.root_node_ids == ("bio_1", "ml_1")
    assert validated_dag.metrics.leaf_node_ids == ("synth_1",)


@pytest.mark.asyncio
async def test_c_parallel_independent_subtasks() -> None:
    """Test C: Parallel independent subtasks with zero interdependencies."""
    llm = MockLLMClient()
    planner = PlannerAgent(llm_client=llm)

    decomp = PlannedDecomposition(
        rationale="Embarrassingly parallel search tasks.",
        subtasks=(
            PlannedSubtask(
                subtask_id="p1",
                task_type=TaskType.WEB_SEARCH,
                objective="Search benchmark A.",
            ),
            PlannedSubtask(
                subtask_id="p2",
                task_type=TaskType.WEB_SEARCH,
                objective="Search benchmark B.",
            ),
            PlannedSubtask(
                subtask_id="p3",
                task_type=TaskType.WEB_SEARCH,
                objective="Search benchmark C.",
            ),
        ),
    )
    llm.set_structured_response(PlannedDecomposition, decomp)

    plan, validated_dag = await planner.plan_and_validate(_make_goal())
    assert len(plan.edges) == 0
    assert validated_dag.metrics.critical_path_depth == 1
    assert len(validated_dag.metrics.root_node_ids) == 3


@pytest.mark.asyncio
async def test_d_dependency_chain() -> None:
    """Test D: Linear dependency chain (t1 -> t2 -> t3)."""
    llm = MockLLMClient()
    planner = PlannerAgent(llm_client=llm)

    decomp = PlannedDecomposition(
        rationale="Sequential pipeline.",
        subtasks=(
            PlannedSubtask(
                subtask_id="step1",
                task_type=TaskType.WEB_SEARCH,
                objective="Gather raw sources.",
            ),
            PlannedSubtask(
                subtask_id="step2",
                task_type=TaskType.DOC_ANALYSIS,
                objective="Extract key factual claims.",
                assigned_role=AgentRole.ANALYST,
                prerequisite_ids=("step1",),
            ),
            PlannedSubtask(
                subtask_id="step3",
                task_type=TaskType.VERIFICATION,
                objective="Audit claims against known ground truth.",
                assigned_role=AgentRole.VERIFIER,
                prerequisite_ids=("step2",),
            ),
        ),
    )
    llm.set_structured_response(PlannedDecomposition, decomp)

    plan, validated_dag = await planner.plan_and_validate(_make_goal())
    assert validated_dag.topological_order == ("step1", "step2", "step3")
    assert validated_dag.metrics.critical_path_depth == 3


@pytest.mark.asyncio
async def test_e_diamond_converging_dependency_graph() -> None:
    """Test E: Diamond dependency topology (A -> B, A -> C, B -> D, C -> D)."""
    llm = MockLLMClient()
    planner = PlannerAgent(llm_client=llm)

    decomp = PlannedDecomposition(
        rationale="Diamond topology.",
        subtasks=(
            PlannedSubtask(
                subtask_id="node_a",
                task_type=TaskType.WEB_SEARCH,
                objective="Initial discovery.",
            ),
            PlannedSubtask(
                subtask_id="node_b",
                task_type=TaskType.DOC_ANALYSIS,
                objective="Deep dive perspective 1.",
                prerequisite_ids=("node_a",),
            ),
            PlannedSubtask(
                subtask_id="node_c",
                task_type=TaskType.DOC_ANALYSIS,
                objective="Deep dive perspective 2.",
                prerequisite_ids=("node_a",),
            ),
            PlannedSubtask(
                subtask_id="node_d",
                task_type=TaskType.SYNTHESIS,
                objective="Synthesize perspectives.",
                prerequisite_ids=("node_b", "node_c"),
            ),
        ),
    )
    llm.set_structured_response(PlannedDecomposition, decomp)

    plan, validated_dag = await planner.plan_and_validate(_make_goal())
    assert validated_dag.topological_order[0] == "node_a"
    assert validated_dag.topological_order[-1] == "node_d"
    assert set(validated_dag.topological_order[1:3]) == {"node_b", "node_c"}
    assert validated_dag.metrics.critical_path_depth == 3


@pytest.mark.asyncio
async def test_f_deterministic_output() -> None:
    """Test F: Repeated calls with identical inputs produce deterministic output."""
    llm = MockLLMClient()
    planner = PlannerAgent(llm_client=llm)

    decomp = PlannedDecomposition(
        rationale="Deterministic check.",
        subtasks=(
            PlannedSubtask(subtask_id="t1", objective="Subtask 1"),
            PlannedSubtask(
                subtask_id="t2", objective="Subtask 2", prerequisite_ids=("t1",)
            ),
        ),
    )
    llm.set_structured_response(PlannedDecomposition, decomp)

    goal = _make_goal()
    plan_1, dag_1 = await planner.plan_and_validate(
        goal, run_id="fixed_run", plan_id="fixed_plan"
    )
    plan_2, dag_2 = await planner.plan_and_validate(
        goal, run_id="fixed_run", plan_id="fixed_plan"
    )

    assert plan_1.model_dump(exclude={"created_at"}) == plan_2.model_dump(
        exclude={"created_at"}
    )
    assert dag_1.topological_order == dag_2.topological_order


@pytest.mark.asyncio
async def test_g_duplicate_subtask_ids_rejected() -> None:
    """Test G: Duplicate subtask IDs in planner output are strictly rejected."""
    llm = MockLLMClient()
    planner = PlannerAgent(llm_client=llm)

    decomp = PlannedDecomposition(
        subtasks=(
            PlannedSubtask(subtask_id="dup_id", objective="First task"),
            PlannedSubtask(subtask_id="dup_id", objective="Second task"),
        ),
    )
    llm.set_structured_response(PlannedDecomposition, decomp)

    with pytest.raises(PlannerError) as exc_info:
        await planner.plan(_make_goal())
    assert "Duplicate subtask_id" in str(exc_info.value)


@pytest.mark.asyncio
async def test_h_dangling_dependency_rejected() -> None:
    """Test H: Dangling prerequisite references to non-existent tasks are rejected."""
    llm = MockLLMClient()
    planner = PlannerAgent(llm_client=llm)

    decomp = PlannedDecomposition(
        subtasks=(
            PlannedSubtask(
                subtask_id="task_1",
                objective="Task 1",
                prerequisite_ids=("ghost_task",),
            ),
        ),
    )
    llm.set_structured_response(PlannedDecomposition, decomp)

    with pytest.raises(DAGValidationError) as exc_info:
        await planner.plan(_make_goal())
    assert exc_info.value.error_code == "MISSING_SOURCE_NODE"


@pytest.mark.asyncio
async def test_i_cyclic_dependency_rejected() -> None:
    """Test I: Cyclic dependencies (A -> B -> A) are detected and rejected."""
    llm = MockLLMClient()
    planner = PlannerAgent(llm_client=llm)

    decomp = PlannedDecomposition(
        subtasks=(
            PlannedSubtask(
                subtask_id="cycle_a",
                objective="Task A",
                prerequisite_ids=("cycle_b",),
            ),
            PlannedSubtask(
                subtask_id="cycle_b",
                objective="Task B",
                prerequisite_ids=("cycle_a",),
            ),
        ),
    )
    llm.set_structured_response(PlannedDecomposition, decomp)

    with pytest.raises(DAGValidationError) as exc_info:
        await planner.plan(_make_goal())
    assert exc_info.value.error_code == "CYCLE_DETECTED"


@pytest.mark.asyncio
async def test_j_invalid_planner_output_rejected() -> None:
    """Test J: Invalid or malformed planner outputs are rejected."""
    llm = MockLLMClient()
    planner = PlannerAgent(llm_client=llm)

    # Empty subtask objective rejected by Pydantic validation
    with pytest.raises(ValidationError):
        PlannedSubtask(subtask_id="t1", objective="")

    # Max subtasks exceeded
    too_many = tuple(
        PlannedSubtask(subtask_id=f"t_{i}", objective=f"Task {i}") for i in range(15)
    )
    decomp = PlannedDecomposition(subtasks=too_many)
    llm.set_structured_response(PlannedDecomposition, decomp)

    goal = _make_goal(max_subtasks=5)
    with pytest.raises(PlannerError) as exc_info:
        await planner.plan(goal)
    assert "exceeds goal max_subtasks" in str(exc_info.value)


@pytest.mark.asyncio
async def test_k_dag_validator_custom_limits_integration() -> None:
    """Test K: Integration with custom DAGValidator limits (e.g. max_depth limit)."""
    llm = MockLLMClient()
    # Enforce strict max_depth of 2
    strict_validator = DAGValidator(max_depth=2)
    planner = PlannerAgent(llm_client=llm, validator=strict_validator)

    # 3-level chain exceeds max_depth of 2
    decomp = PlannedDecomposition(
        subtasks=(
            PlannedSubtask(subtask_id="d1", objective="Depth 1"),
            PlannedSubtask(
                subtask_id="d2", objective="Depth 2", prerequisite_ids=("d1",)
            ),
            PlannedSubtask(
                subtask_id="d3", objective="Depth 3", prerequisite_ids=("d2",)
            ),
        ),
    )
    llm.set_structured_response(PlannedDecomposition, decomp)

    with pytest.raises(DAGValidationError) as exc_info:
        await planner.plan(_make_goal())
    assert exc_info.value.error_code == "MAX_DEPTH_EXCEEDED"


@pytest.mark.asyncio
async def test_l_planner_output_consumed_by_dag_executor() -> None:
    """Test L: Direct execution of PlannerAgent output by Phase 2 DAGExecutor."""
    llm = MockLLMClient()
    planner = PlannerAgent(llm_client=llm)

    decomp = PlannedDecomposition(
        rationale="Executable plan.",
        subtasks=(
            PlannedSubtask(
                subtask_id="step_a",
                task_type=TaskType.WEB_SEARCH,
                objective="Fetch online papers.",
                assigned_role=AgentRole.RESEARCHER,
            ),
            PlannedSubtask(
                subtask_id="step_b",
                task_type=TaskType.SYNTHESIS,
                objective="Synthesize fetched papers.",
                assigned_role=AgentRole.ANALYST,
                prerequisite_ids=("step_a",),
            ),
        ),
    )
    llm.set_structured_response(PlannedDecomposition, decomp)

    plan = await planner.plan(_make_goal())

    executor = DAGExecutor(max_concurrency=2)
    result = await executor.execute_plan(plan)

    assert result.is_success is True
    assert result.status == RunStage.COMPLETED
    assert result.completed_task_ids == ("step_a", "step_b")
    assert len(result.failed_task_ids) == 0
