"""Unit tests for asynchronous concurrency control and execution boundaries."""

import asyncio

import pytest

from app.common.enums import AgentRole, TaskType
from app.orchestration.contracts import AgentRequest, WorkerResponseEnvelope
from app.orchestration.executor import DAGExecutor
from app.orchestration.protocols import WorkerProtocol
from app.orchestration.worker import MockWorker, WorkerRegistry
from app.state.models import DependencyEdge, ResearchGoal, ResearchPlan, SubtaskNode


class ConcurrencyTrackingWorker(WorkerProtocol):
    """Worker that records peak simultaneous active executions."""

    def __init__(self, delay_seconds: float = 0.02) -> None:
        self.delay_seconds = delay_seconds
        self.current_concurrency = 0
        self.peak_concurrency = 0
        self._lock = asyncio.Lock()
        self.worker_id = "tracking-worker"

    async def execute(self, request: AgentRequest) -> WorkerResponseEnvelope:
        async with self._lock:
            self.current_concurrency += 1
            if self.current_concurrency > self.peak_concurrency:
                self.peak_concurrency = self.current_concurrency

        try:
            await asyncio.sleep(self.delay_seconds)
        finally:
            async with self._lock:
                self.current_concurrency -= 1

        mock_delegate = MockWorker(worker_id=self.worker_id)
        return await mock_delegate.execute(request)


@pytest.mark.asyncio
async def test_max_concurrency_boundary_enforced() -> None:
    """Verify DAGExecutor never exceeds configured max_concurrency even with 6 parallel tasks."""
    worker = ConcurrencyTrackingWorker(delay_seconds=0.03)

    nodes = {
        f"t{i}": SubtaskNode(
            subtask_id=f"t{i}",
            task_type=TaskType.WEB_SEARCH,
            objective=f"Task {i}",
            assigned_role=AgentRole.RESEARCHER,
        )
        for i in range(1, 7)
    }

    goal = ResearchGoal(goal_id="g_conc", query="Concurrency limit test")
    plan = ResearchPlan(
        plan_id="p_conc",
        run_id="run_conc_01",
        goal=goal,
        nodes=nodes,
        edges=(),  # All 6 tasks are independent roots
    )

    # Configure executor with max_concurrency = 2
    executor = DAGExecutor(
        max_concurrency=2,
        worker_registry=WorkerRegistry(default_worker=worker),
    )

    result = await executor.execute_plan(plan)

    assert result.is_success is True
    assert len(result.completed_task_ids) == 6
    # Peak concurrency must never exceed 2
    assert worker.peak_concurrency <= 2


@pytest.mark.asyncio
async def test_parallel_independent_branches_merge_correctly() -> None:
    """Verify two independent parallel pipelines (A1->A2 and B1->B2) merge at C."""
    worker = MockWorker()

    nodes = {
        "A1": SubtaskNode(
            subtask_id="A1", task_type=TaskType.WEB_SEARCH, objective="A1"
        ),
        "A2": SubtaskNode(
            subtask_id="A2", task_type=TaskType.WEB_SEARCH, objective="A2"
        ),
        "B1": SubtaskNode(
            subtask_id="B1", task_type=TaskType.WEB_SEARCH, objective="B1"
        ),
        "B2": SubtaskNode(
            subtask_id="B2", task_type=TaskType.WEB_SEARCH, objective="B2"
        ),
        "C": SubtaskNode(subtask_id="C", task_type=TaskType.SYNTHESIS, objective="C"),
    }
    edges = (
        DependencyEdge(source_id="A1", target_id="A2"),
        DependencyEdge(source_id="B1", target_id="B2"),
        DependencyEdge(source_id="A2", target_id="C"),
        DependencyEdge(source_id="B2", target_id="C"),
    )

    goal = ResearchGoal(goal_id="g_merge", query="Merge test")
    plan = ResearchPlan(
        plan_id="p_merge",
        run_id="run_merge_01",
        goal=goal,
        nodes=nodes,
        edges=edges,
    )

    executor = DAGExecutor(worker_registry=WorkerRegistry(default_worker=worker))
    result = await executor.execute_plan(plan)

    assert result.is_success is True
    assert len(result.completed_task_ids) == 5
