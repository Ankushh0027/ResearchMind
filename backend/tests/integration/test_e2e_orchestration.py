"""End-to-End integration tests for Phase 4.3 DAGExecutor, AgentWorkerRouter, and specialized agent mesh."""

import asyncio

import pytest

from app.common.enums import (
    AgentRole,
    EdgeType,
    RunStage,
    TaskStatus,
    TaskType,
)
from app.orchestration.cancellation import CancellationToken
from app.orchestration.contracts import AgentRequest, WorkerResponseEnvelope
from app.orchestration.executor import DAGExecutor, ExecutionResult
from app.orchestration.router import create_default_worker_router
from app.orchestration.runtime import InMemoryCheckpointRepository, InMemoryEventSink
from app.state.models import (
    DependencyEdge,
    ResearchGoal,
    ResearchPlan,
    SubtaskNode,
)


def _build_planner_request(
    run_id: str,
    goal_query: str,
) -> AgentRequest:
    return AgentRequest(
        request_id=f"req_plan_{run_id}",
        run_id=run_id,
        subtask_id="task_planner",
        agent_role=AgentRole.PLANNER,
        task_type=TaskType.DECOMPOSITION,
        goal_context=goal_query,
        input_data={"goal_query": goal_query},
        idempotency_key=f"idem_plan_{run_id}",
    )


@pytest.mark.asyncio
async def test_e2e_research_pipeline_execution() -> None:
    """Test 1 E2E: Execute full multi-agent research pipeline from Planner decomposition to final ResearchDossier."""
    router = create_default_worker_router()
    run_id = "run_e2e_001"
    goal_query = (
        "What are the mechanisms of high-temperature superconductivity in cuprates?"
    )

    # Step 1: PlannerWorker decomposes the research goal into subtasks
    plan_req = _build_planner_request(run_id, goal_query)
    plan_env: WorkerResponseEnvelope = await router.execute(plan_req)

    assert plan_env.status == TaskStatus.COMPLETED
    assert plan_env.response is not None
    output_data = plan_env.response.output_data
    assert "planned_subtasks" in output_data

    # Step 2: Build execution DAG representing the multi-agent research workflow
    goal = ResearchGoal(
        goal_id=f"goal_{run_id}",
        query=goal_query,
    )

    # Node 1: Researcher (Web Search)
    node_res1 = SubtaskNode(
        subtask_id="task_res_01",
        task_type=TaskType.WEB_SEARCH,
        objective="Search literature on cuprate d-wave symmetry",
        search_queries=("cuprates electronic nematicity d-wave",),
        assigned_role=AgentRole.RESEARCHER,
        input_context={"queries": ["cuprates electronic nematicity d-wave"]},
    )

    # Node 2: Researcher (Academic Search)
    node_res2 = SubtaskNode(
        subtask_id="task_res_02",
        task_type=TaskType.ACADEMIC_SEARCH,
        objective="Search academic articles on cuprate critical temperatures",
        search_queries=("cuprate transition temperature spin fluctuations",),
        assigned_role=AgentRole.RESEARCHER,
        input_context={"queries": ["cuprate transition temperature spin fluctuations"]},
    )

    # Node 3: Analyst (Synthesis) - Depends on Node 1 & Node 2
    node_analyst = SubtaskNode(
        subtask_id="task_an_01",
        task_type=TaskType.SYNTHESIS,
        objective="Synthesize factual claims and thematic findings from retrieved evidence",
        assigned_role=AgentRole.ANALYST,
    )

    # Node 4: Verifier (Verification & Conflict Detection) - Depends on Node 1, 2, 3
    node_verifier = SubtaskNode(
        subtask_id="task_ver_01",
        task_type=TaskType.VERIFICATION,
        objective="Verify factual grounding and map citations",
        assigned_role=AgentRole.VERIFIER,
    )

    # Node 5: Evaluator (Quality Assessment) - Depends on Node 3 & Node 4
    node_evaluator = SubtaskNode(
        subtask_id="task_eval_01",
        task_type=TaskType.EVALUATION,
        objective="Evaluate research synthesis quality and completeness",
        assigned_role=AgentRole.EVALUATOR,
        input_context={"goal_query": goal_query},
    )

    # Node 6: Reporter (Dossier Compilation) - Depends on Node 3, 4, 5
    node_reporter = SubtaskNode(
        subtask_id="task_rep_01",
        task_type=TaskType.REPORTING,
        objective="Compile publication-ready ResearchDossier and Markdown deliverable",
        assigned_role=AgentRole.REPORTER,
        input_context={"goal_query": goal_query},
    )

    nodes = {
        node_res1.subtask_id: node_res1,
        node_res2.subtask_id: node_res2,
        node_analyst.subtask_id: node_analyst,
        node_verifier.subtask_id: node_verifier,
        node_evaluator.subtask_id: node_evaluator,
        node_reporter.subtask_id: node_reporter,
    }

    edges = (
        # Parallel researchers -> Analyst
        DependencyEdge(
            source_id="task_res_01", target_id="task_an_01", edge_type=EdgeType.DATA
        ),
        DependencyEdge(
            source_id="task_res_02", target_id="task_an_01", edge_type=EdgeType.DATA
        ),
        # Researchers + Analyst -> Verifier
        DependencyEdge(
            source_id="task_res_01", target_id="task_ver_01", edge_type=EdgeType.DATA
        ),
        DependencyEdge(
            source_id="task_res_02", target_id="task_ver_01", edge_type=EdgeType.DATA
        ),
        DependencyEdge(
            source_id="task_an_01", target_id="task_ver_01", edge_type=EdgeType.DATA
        ),
        # Analyst + Verifier -> Evaluator
        DependencyEdge(
            source_id="task_an_01", target_id="task_eval_01", edge_type=EdgeType.DATA
        ),
        DependencyEdge(
            source_id="task_ver_01", target_id="task_eval_01", edge_type=EdgeType.DATA
        ),
        # Analyst + Verifier + Evaluator -> Reporter
        DependencyEdge(
            source_id="task_an_01", target_id="task_rep_01", edge_type=EdgeType.DATA
        ),
        DependencyEdge(
            source_id="task_ver_01", target_id="task_rep_01", edge_type=EdgeType.DATA
        ),
        DependencyEdge(
            source_id="task_eval_01", target_id="task_rep_01", edge_type=EdgeType.DATA
        ),
    )

    plan = ResearchPlan(
        plan_id=f"plan_{run_id}",
        run_id=run_id,
        goal=goal,
        nodes=nodes,
        edges=edges,
    )

    # Step 3: Execute the research DAG via DAGExecutor configured with AgentWorkerRouter
    checkpoint_repo = InMemoryCheckpointRepository()
    event_sink = InMemoryEventSink()
    executor = DAGExecutor(
        max_concurrency=4,
        worker_registry=router,
        checkpoint_repo=checkpoint_repo,
        event_sink=event_sink,
    )

    result: ExecutionResult = await executor.execute_plan(plan)

    # Step 4: Verify execution completion and contract deliverables
    assert result.is_success is True
    assert result.status == RunStage.COMPLETED
    assert len(result.completed_task_ids) == 6
    assert len(result.failed_task_ids) == 0

    # Step 5: Verify final ResearchDossier from ReporterWorker
    reporter_out = result.task_outputs["task_rep_01"]
    assert "dossier_id" in reporter_out
    assert "markdown_report" in reporter_out
    assert len(reporter_out["key_findings"]) >= 1
    assert len(reporter_out["citations"]) >= 1
    assert "## Executive Summary" in reporter_out["markdown_report"]
    assert "## Comprehensive Bibliography & Sources" in reporter_out["markdown_report"]


@pytest.mark.asyncio
async def test_e2e_upstream_failure_blocks_downstream_tasks() -> None:
    """Test 2: Verify failure in an upstream task halts dependent downstream tasks."""

    class FailingResearcherWorker:
        async def execute(self, request: AgentRequest) -> WorkerResponseEnvelope:
            return WorkerResponseEnvelope(
                envelope_id=f"env_fail_{request.request_id}",
                dispatch_id=f"disp_{request.request_id}",
                run_id=request.run_id,
                subtask_id=request.subtask_id,
                status=TaskStatus.FAILED,
                error=None,
                worker_id="failing-researcher",
            )

    router = create_default_worker_router(researcher_worker=FailingResearcherWorker())
    run_id = "run_fail_001"
    goal = ResearchGoal(goal_id=f"goal_{run_id}", query="Inquiry that will fail")

    node_res = SubtaskNode(
        subtask_id="task_res_01",
        task_type=TaskType.WEB_SEARCH,
        objective="Search literature",
        assigned_role=AgentRole.RESEARCHER,
    )
    node_an = SubtaskNode(
        subtask_id="task_an_01",
        task_type=TaskType.SYNTHESIS,
        objective="Synthesize",
        assigned_role=AgentRole.ANALYST,
    )

    nodes = {node_res.subtask_id: node_res, node_an.subtask_id: node_an}
    edges = (DependencyEdge(source_id="task_res_01", target_id="task_an_01"),)

    plan = ResearchPlan(
        plan_id=f"plan_{run_id}", run_id=run_id, goal=goal, nodes=nodes, edges=edges
    )

    executor = DAGExecutor(worker_registry=router)
    result = await executor.execute_plan(plan)

    assert result.is_success is False
    assert result.status == RunStage.FAILED
    assert "task_res_01" in result.failed_task_ids
    assert "task_an_01" not in result.completed_task_ids


@pytest.mark.asyncio
async def test_e2e_cooperative_cancellation() -> None:
    """Test 3: Verify cancellation token cancels running and scheduled tasks gracefully."""
    router = create_default_worker_router()
    run_id = "run_cancel_001"
    token = CancellationToken()
    token.cancel(reason="Execution stopped by user")

    goal = ResearchGoal(goal_id=f"goal_{run_id}", query="Cancelled inquiry")
    node_res = SubtaskNode(
        subtask_id="task_res_01",
        task_type=TaskType.WEB_SEARCH,
        objective="Search literature",
        assigned_role=AgentRole.RESEARCHER,
    )

    plan = ResearchPlan(
        plan_id=f"plan_{run_id}",
        run_id=run_id,
        goal=goal,
        nodes={node_res.subtask_id: node_res},
        edges=(),
    )

    executor = DAGExecutor(worker_registry=router)
    result = await executor.execute_plan(plan, cancellation_token=token)

    assert result.status == RunStage.CANCELLED
    assert "task_res_01" in result.cancelled_task_ids


@pytest.mark.asyncio
async def test_e2e_multi_tenant_isolation() -> None:
    """Test 4: Verify concurrent runs remain strictly isolated in memory and outputs."""
    router = create_default_worker_router()

    async def _run_pipeline(tenant_id: str, topic: str) -> ExecutionResult:
        run_id = f"run_{tenant_id}"
        goal = ResearchGoal(goal_id=f"goal_{run_id}", query=topic)
        node_res = SubtaskNode(
            subtask_id="task_res_01",
            task_type=TaskType.WEB_SEARCH,
            objective=f"Search {topic}",
            assigned_role=AgentRole.RESEARCHER,
            input_context={"queries": [topic]},
        )
        node_an = SubtaskNode(
            subtask_id="task_an_01",
            task_type=TaskType.SYNTHESIS,
            objective="Synthesize",
            assigned_role=AgentRole.ANALYST,
        )
        plan = ResearchPlan(
            plan_id=f"plan_{run_id}",
            run_id=run_id,
            goal=goal,
            nodes={node_res.subtask_id: node_res, node_an.subtask_id: node_an},
            edges=(DependencyEdge(source_id="task_res_01", target_id="task_an_01"),),
        )
        executor = DAGExecutor(worker_registry=router)
        return await executor.execute_plan(plan)

    res_a, res_b = await asyncio.gather(
        _run_pipeline("tenant_A", "Cuprate superconductivity"),
        _run_pipeline("tenant_B", "Quantum topological insulators"),
    )

    assert res_a.is_success is True
    assert res_a.run_id == "run_tenant_A"
    assert res_b.is_success is True
    assert res_b.run_id == "run_tenant_B"
