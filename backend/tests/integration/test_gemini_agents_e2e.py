"""End-to-end integration tests verifying agent reasoning over GeminiLLMClient adapter."""

import pytest

from app.adapters.llm.gemini import GeminiLLMClient
from app.agents.planner.worker import PlannerWorker
from app.common.enums import AgentRole, TaskStatus, TaskType
from app.intelligence.planner import PlannedDecomposition, PlannedSubtask, PlannerAgent
from app.orchestration.contracts import AgentRequest
from app.orchestration.router import create_default_worker_router
from app.state.models import ResearchGoal
from tests.unit.test_gemini_llm import FakeGenAIClient, FakeGenerateContentResponse


@pytest.mark.asyncio
async def test_planner_agent_with_gemini_adapter_e2e() -> None:
    """Test 1: Verify PlannerAgent generates validated DAG from GeminiLLMClient structured output."""
    sample_decomp = PlannedDecomposition(
        rationale="Decompose quantum inquiry into search and synthesis tasks.",
        subtasks=(
            PlannedSubtask(
                subtask_id="task_01",
                task_type=TaskType.WEB_SEARCH,
                objective="Search for topological quantum memory papers.",
                search_queries=(
                    "topological quantum memory",
                    "surface code benchmarks",
                ),
                assigned_role=AgentRole.RESEARCHER,
                prerequisite_ids=(),
            ),
            PlannedSubtask(
                subtask_id="task_02",
                task_type=TaskType.SYNTHESIS,
                objective="Synthesize error suppression metrics.",
                search_queries=(),
                assigned_role=AgentRole.ANALYST,
                prerequisite_ids=("task_01",),
            ),
        ),
    )

    client = FakeGenAIClient()
    client.aio.models.side_effects = [
        FakeGenerateContentResponse(text=sample_decomp.model_dump_json())
    ]

    llm = GeminiLLMClient(
        api_key="fake-gemini-key",
        model_name="gemini-2.5-pro",
        client=client,
    )

    agent = PlannerAgent(llm_client=llm)
    goal = ResearchGoal(
        goal_id="goal_quantum_01",
        query="Investigate topological quantum memories.",
        domain_tags=("quantum", "physics"),
        max_subtasks=5,
    )

    plan, validated_dag = await agent.plan_and_validate(
        goal=goal, run_id="run_quantum_01"
    )

    assert plan.run_id == "run_quantum_01"
    assert len(plan.nodes) == 2
    assert "task_01" in plan.nodes
    assert "task_02" in plan.nodes
    assert plan.is_validated is True
    assert validated_dag.topological_order == ("task_01", "task_02")
    assert validated_dag.metrics.node_count == 2
    assert validated_dag.metrics.edge_count == 1


@pytest.mark.asyncio
async def test_agent_worker_router_with_gemini_planner_worker_e2e() -> None:
    """Test 2: Verify AgentWorkerRouter dispatching through PlannerWorker backed by GeminiLLMClient."""
    sample_decomp = PlannedDecomposition(
        rationale="Router decomposition execution.",
        subtasks=(
            PlannedSubtask(
                subtask_id="task_q1",
                task_type=TaskType.WEB_SEARCH,
                objective="Query primary quantum sources.",
                assigned_role=AgentRole.RESEARCHER,
            ),
            PlannedSubtask(
                subtask_id="task_q2",
                task_type=TaskType.REPORTING,
                objective="Compile research report.",
                assigned_role=AgentRole.REPORTER,
                prerequisite_ids=("task_q1",),
            ),
        ),
    )

    client = FakeGenAIClient()
    client.aio.models.side_effects = [
        FakeGenerateContentResponse(text=sample_decomp.model_dump_json())
    ]

    llm = GeminiLLMClient(api_key="fake-key", client=client)
    planner_worker = PlannerWorker(
        planner_agent=PlannerAgent(llm_client=llm),
        worker_id="planner-gemini-worker",
    )

    router = create_default_worker_router(planner_worker=planner_worker)

    request = AgentRequest(
        request_id="req_decomp_01",
        run_id="run_router_gemini_01",
        subtask_id="task_init_decomp",
        task_type=TaskType.DECOMPOSITION,
        agent_role=AgentRole.PLANNER,
        goal_context="Explore error mitigation strategies.",
        idempotency_key="idemp_decomp_01",
    )

    envelope = await router.execute(request)
    assert envelope.status == TaskStatus.COMPLETED
    assert envelope.worker_id == "planner-gemini-worker"
    assert envelope.response is not None
    assert envelope.response.output_data.get("plan_id") is not None
    assert len(envelope.response.output_data.get("planned_subtasks", [])) == 2
