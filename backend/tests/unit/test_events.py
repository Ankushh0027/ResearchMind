"""Unit tests for typed execution event emission and observability tracking."""

import pytest

from app.common.enums import AgentRole, TaskType
from app.orchestration.contracts import TokenUsage
from app.orchestration.events import (
    RunStartedEvent,
    TaskCompletedEvent,
)
from app.orchestration.executor import DAGExecutor
from app.orchestration.runtime import InMemoryEventSink, MetricsCollector
from app.orchestration.worker import MockWorker, MockWorkerBehavior, WorkerRegistry
from app.state.models import ResearchGoal, ResearchPlan, SubtaskNode


@pytest.mark.asyncio
async def test_event_emission_sequence_and_correlation_ids() -> None:
    """Verify standard execution emits correlated typed events in chronological order."""
    sink = InMemoryEventSink()
    metrics = MetricsCollector()

    worker = MockWorker(
        default_behavior=MockWorkerBehavior(
            token_usage=TokenUsage(
                prompt_tokens=100, completion_tokens=50, total_tokens=150
            )
        )
    )

    node = SubtaskNode(
        subtask_id="task_evt",
        task_type=TaskType.WEB_SEARCH,
        objective="Event test task",
        assigned_role=AgentRole.RESEARCHER,
    )
    goal = ResearchGoal(goal_id="g_evt", query="Event test query")
    plan = ResearchPlan(
        plan_id="plan_evt_01",
        run_id="run_evt_01",
        goal=goal,
        nodes={"task_evt": node},
        edges=(),
    )

    executor = DAGExecutor(
        worker_registry=WorkerRegistry(default_worker=worker),
        event_sink=sink,
        observability_hook=metrics,
    )

    result = await executor.execute_plan(plan)
    assert result.is_success is True

    events = sink.get_events("run_evt_01")
    event_types = [e.event_type for e in events]

    expected_sequence = [
        "run_started",
        "task_scheduled",
        "task_started",
        "task_completed",
        "run_completed",
    ]
    assert event_types == expected_sequence

    # Verify correlation fields on RunStartedEvent
    run_started = events[0]
    assert isinstance(run_started, RunStartedEvent)
    assert run_started.run_id == "run_evt_01"
    assert run_started.plan_id == "plan_evt_01"

    # Verify TaskCompletedEvent tokens
    task_completed = events[3]
    assert isinstance(task_completed, TaskCompletedEvent)
    assert task_completed.subtask_id == "task_evt"
    assert task_completed.token_usage.total_tokens == 150

    # Verify MetricsCollector
    assert metrics.runs_started == 1
    assert metrics.runs_completed == 1
    assert metrics.tasks_completed == 1
    assert metrics.total_token_usage.total_tokens == 150
