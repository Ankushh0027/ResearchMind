"""Unit tests for Phase 4.3 DAGExecutor with AgentWorkerRouter and specialized agent mesh."""

import asyncio

import pytest

from app.common.enums import (
    AgentRole,
    EdgeType,
    RunStage,
    TaskStatus,
    TaskType,
)
from app.common.errors import DAGValidationError
from app.orchestration.cancellation import CancellationToken
from app.orchestration.contracts import (
    AgentError,
    AgentRequest,
    AgentResponse,
    TokenUsage,
    WorkerResponseEnvelope,
)
from app.orchestration.executor import DAGExecutor, ExecutionResult
from app.orchestration.protocols import WorkerProtocol
from app.orchestration.router import AgentWorkerRouter, create_default_worker_router
from app.state.models import (
    DependencyEdge,
    ResearchGoal,
    ResearchPlan,
    SubtaskNode,
)


class MockTrackingWorker(WorkerProtocol):
    """Mock worker recording all received requests and returning configurable responses."""

    def __init__(self, worker_id: str = "mock-tracker-01") -> None:
        self.worker_id = worker_id
        self.invocations: list[AgentRequest] = []
        self.failure_subtasks: set[str] = set()
        self.delay_seconds: float = 0.0

    async def execute(self, request: AgentRequest) -> WorkerResponseEnvelope:
        self.invocations.append(request)
        if self.delay_seconds > 0:
            await asyncio.sleep(self.delay_seconds)

        if request.subtask_id in self.failure_subtasks:
            err = AgentError(
                error_code="SUBTASK_EXECUTION_FAILED",
                error_type="WorkerExecutionError",
                message=f"Simulated failure on {request.subtask_id}",
                is_retryable=False,
            )
            return WorkerResponseEnvelope(
                envelope_id=f"env_fail_{request.request_id}",
                dispatch_id=f"disp_{request.request_id}",
                run_id=request.run_id,
                subtask_id=request.subtask_id,
                status=TaskStatus.FAILED,
                error=err,
                worker_id=self.worker_id,
            )

        resp = AgentResponse(
            response_id=f"resp_{request.request_id}",
            request_id=request.request_id,
            run_id=request.run_id,
            subtask_id=request.subtask_id,
            agent_role=request.agent_role,
            output_data={
                "result": f"success_{request.subtask_id}",
                "echo_role": request.agent_role.value,
            },
            execution_time_ms=10,
            token_usage=TokenUsage(
                prompt_tokens=15, completion_tokens=25, total_tokens=40
            ),
            error=None,
        )
        return WorkerResponseEnvelope(
            envelope_id=f"env_{request.request_id}",
            dispatch_id=f"disp_{request.request_id}",
            run_id=request.run_id,
            subtask_id=request.subtask_id,
            status=TaskStatus.COMPLETED,
            response=resp,
            error=None,
            worker_id=self.worker_id,
        )


def _make_plan(
    run_id: str = "run_exec_01",
    nodes: dict[str, SubtaskNode] | None = None,
    edges: tuple[DependencyEdge, ...] = (),
) -> ResearchPlan:
    goal = ResearchGoal(
        goal_id=f"goal_{run_id}", query="Autonomous Multi-Agent Investigation"
    )
    if nodes is None:
        node = SubtaskNode(
            subtask_id="task_01",
            task_type=TaskType.WEB_SEARCH,
            objective="Search web for baseline facts",
            assigned_role=AgentRole.RESEARCHER,
            input_context={"queries": ["superconductivity"]},
        )
        nodes = {node.subtask_id: node}

    return ResearchPlan(
        plan_id=f"plan_{run_id}",
        run_id=run_id,
        goal=goal,
        nodes=nodes,
        edges=edges,
    )


@pytest.mark.asyncio
async def test_single_node_execution() -> None:
    """Test 1: Verify DAGExecutor executes a single-node plan successfully through router."""
    router = create_default_worker_router()
    plan = _make_plan()
    executor = DAGExecutor(worker_registry=router)

    result: ExecutionResult = await executor.execute_plan(plan)

    assert result.is_success is True
    assert result.status == RunStage.COMPLETED
    assert result.completed_task_ids == ("task_01",)
    assert len(result.failed_task_ids) == 0


@pytest.mark.asyncio
async def test_linear_multi_node_dependency_ordering() -> None:
    """Test 2: Verify multi-node linear DAG executes strictly in dependency order."""
    tracker = MockTrackingWorker()
    router = AgentWorkerRouter()
    router.register_worker(
        tracker, role=AgentRole.RESEARCHER, task_types=(TaskType.WEB_SEARCH,)
    )
    router.register_worker(
        tracker, role=AgentRole.ANALYST, task_types=(TaskType.SYNTHESIS,)
    )
    router.register_worker(
        tracker, role=AgentRole.REPORTER, task_types=(TaskType.REPORTING,)
    )

    n1 = SubtaskNode(
        subtask_id="step_1",
        task_type=TaskType.WEB_SEARCH,
        objective="Search",
        assigned_role=AgentRole.RESEARCHER,
    )
    n2 = SubtaskNode(
        subtask_id="step_2",
        task_type=TaskType.SYNTHESIS,
        objective="Synthesize",
        assigned_role=AgentRole.ANALYST,
    )
    n3 = SubtaskNode(
        subtask_id="step_3",
        task_type=TaskType.REPORTING,
        objective="Report",
        assigned_role=AgentRole.REPORTER,
    )

    nodes = {n1.subtask_id: n1, n2.subtask_id: n2, n3.subtask_id: n3}
    edges = (
        DependencyEdge(source_id="step_1", target_id="step_2", edge_type=EdgeType.DATA),
        DependencyEdge(source_id="step_2", target_id="step_3", edge_type=EdgeType.DATA),
    )
    plan = _make_plan(nodes=nodes, edges=edges)

    executor = DAGExecutor(worker_registry=router)
    result = await executor.execute_plan(plan)

    assert result.is_success is True
    assert len(tracker.invocations) == 3
    invoked_order = [req.subtask_id for req in tracker.invocations]
    assert invoked_order == ["step_1", "step_2", "step_3"]


@pytest.mark.asyncio
async def test_branching_and_fan_in_dag() -> None:
    """Test 3: Verify diamond/fan-in DAG executes parallel branches and waits at join node."""
    tracker = MockTrackingWorker()
    router = AgentWorkerRouter()
    router.register_worker(
        tracker,
        role=AgentRole.RESEARCHER,
        task_types=(TaskType.WEB_SEARCH, TaskType.ACADEMIC_SEARCH),
    )
    router.register_worker(
        tracker, role=AgentRole.ANALYST, task_types=(TaskType.SYNTHESIS,)
    )

    # Root -> (Branch A, Branch B) -> Join Node
    n_root = SubtaskNode(
        subtask_id="n_root",
        task_type=TaskType.WEB_SEARCH,
        objective="Root Search",
        assigned_role=AgentRole.RESEARCHER,
    )
    n_a = SubtaskNode(
        subtask_id="n_branch_a",
        task_type=TaskType.WEB_SEARCH,
        objective="Branch A",
        assigned_role=AgentRole.RESEARCHER,
    )
    n_b = SubtaskNode(
        subtask_id="n_branch_b",
        task_type=TaskType.ACADEMIC_SEARCH,
        objective="Branch B",
        assigned_role=AgentRole.RESEARCHER,
    )
    n_join = SubtaskNode(
        subtask_id="n_join",
        task_type=TaskType.SYNTHESIS,
        objective="Join Synthesis",
        assigned_role=AgentRole.ANALYST,
    )

    nodes = {
        n_root.subtask_id: n_root,
        n_a.subtask_id: n_a,
        n_b.subtask_id: n_b,
        n_join.subtask_id: n_join,
    }
    edges = (
        DependencyEdge(
            source_id="n_root", target_id="n_branch_a", edge_type=EdgeType.DATA
        ),
        DependencyEdge(
            source_id="n_root", target_id="n_branch_b", edge_type=EdgeType.DATA
        ),
        DependencyEdge(
            source_id="n_branch_a", target_id="n_join", edge_type=EdgeType.DATA
        ),
        DependencyEdge(
            source_id="n_branch_b", target_id="n_join", edge_type=EdgeType.DATA
        ),
    )
    plan = _make_plan(nodes=nodes, edges=edges)

    executor = DAGExecutor(max_concurrency=4, worker_registry=router)
    result = await executor.execute_plan(plan)

    assert result.is_success is True
    assert len(result.completed_task_ids) == 4

    invoked_ids = [req.subtask_id for req in tracker.invocations]
    assert invoked_ids[0] == "n_root"
    assert set(invoked_ids[1:3]) == {"n_branch_a", "n_branch_b"}
    assert invoked_ids[3] == "n_join"


@pytest.mark.asyncio
async def test_invalid_dag_cycle_detection() -> None:
    """Test 4: Verify cyclic dependency in plan raises DAGValidationError before execution."""
    n1 = SubtaskNode(
        subtask_id="node_1",
        task_type=TaskType.WEB_SEARCH,
        objective="Search 1",
        assigned_role=AgentRole.RESEARCHER,
    )
    n2 = SubtaskNode(
        subtask_id="node_2",
        task_type=TaskType.WEB_SEARCH,
        objective="Search 2",
        assigned_role=AgentRole.RESEARCHER,
    )

    nodes = {n1.subtask_id: n1, n2.subtask_id: n2}
    edges = (
        DependencyEdge(source_id="node_1", target_id="node_2"),
        DependencyEdge(source_id="node_2", target_id="node_1"),
    )
    plan = _make_plan(nodes=nodes, edges=edges)

    executor = DAGExecutor()
    with pytest.raises(DAGValidationError):
        await executor.execute_plan(plan)


@pytest.mark.asyncio
async def test_upstream_failure_prevents_downstream_execution() -> None:
    """Test 5: Verify failing task blocks dependent tasks from executing."""
    tracker = MockTrackingWorker()
    tracker.failure_subtasks.add("node_failed")

    router = AgentWorkerRouter()
    router.register_worker(
        tracker, role=AgentRole.RESEARCHER, task_types=(TaskType.WEB_SEARCH,)
    )
    router.register_worker(
        tracker, role=AgentRole.ANALYST, task_types=(TaskType.SYNTHESIS,)
    )

    n1 = SubtaskNode(
        subtask_id="node_failed",
        task_type=TaskType.WEB_SEARCH,
        objective="Fails",
        assigned_role=AgentRole.RESEARCHER,
    )
    n2 = SubtaskNode(
        subtask_id="node_blocked",
        task_type=TaskType.SYNTHESIS,
        objective="Blocked",
        assigned_role=AgentRole.ANALYST,
    )

    nodes = {n1.subtask_id: n1, n2.subtask_id: n2}
    edges = (DependencyEdge(source_id="node_failed", target_id="node_blocked"),)
    plan = _make_plan(nodes=nodes, edges=edges)

    executor = DAGExecutor(worker_registry=router)
    result = await executor.execute_plan(plan)

    assert result.is_success is False
    assert result.status == RunStage.FAILED
    assert "node_failed" in result.failed_task_ids
    assert "node_blocked" not in result.completed_task_ids
    assert len(tracker.invocations) == 1
    assert tracker.invocations[0].subtask_id == "node_failed"


@pytest.mark.asyncio
async def test_cancellation_during_execution() -> None:
    """Test 6: Verify signalling CancellationToken aborts pending tasks cleanly."""
    token = CancellationToken()
    tracker = MockTrackingWorker()
    tracker.delay_seconds = 0.1

    router = AgentWorkerRouter(cancellation_token=token)
    router.register_worker(
        tracker, role=AgentRole.RESEARCHER, task_types=(TaskType.WEB_SEARCH,)
    )

    n1 = SubtaskNode(
        subtask_id="task_1",
        task_type=TaskType.WEB_SEARCH,
        objective="Search 1",
        assigned_role=AgentRole.RESEARCHER,
    )
    n2 = SubtaskNode(
        subtask_id="task_2",
        task_type=TaskType.WEB_SEARCH,
        objective="Search 2",
        assigned_role=AgentRole.RESEARCHER,
    )

    nodes = {n1.subtask_id: n1, n2.subtask_id: n2}
    edges = (DependencyEdge(source_id="task_1", target_id="task_2"),)
    plan = _make_plan(nodes=nodes, edges=edges)

    executor = DAGExecutor(worker_registry=router)

    async def _cancel_soon() -> None:
        await asyncio.sleep(0.02)
        token.cancel(reason="Aborted by user")

    _, result = await asyncio.gather(
        _cancel_soon(), executor.execute_plan(plan, cancellation_token=token)
    )

    assert result.status == RunStage.CANCELLED


@pytest.mark.asyncio
async def test_router_dispatch_boundary_preservation() -> None:
    """Test 7: Verify DAGExecutor dispatches strictly through WorkerProtocol router."""
    tracker = MockTrackingWorker(worker_id="strict-router-target")
    router = AgentWorkerRouter()
    router.register_worker(
        tracker, role=AgentRole.RESEARCHER, task_types=(TaskType.WEB_SEARCH,)
    )

    plan = _make_plan()
    executor = DAGExecutor(worker_registry=router)
    result = await executor.execute_plan(plan)

    assert result.is_success is True
    assert len(tracker.invocations) == 1
    assert tracker.invocations[0].agent_role == AgentRole.RESEARCHER
    assert tracker.invocations[0].task_type == TaskType.WEB_SEARCH
