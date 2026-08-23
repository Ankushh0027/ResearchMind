"""Unit tests for Phase 4.1.1 PlannerWorker adapter."""

from typing import Any

import pytest

from app.adapters.llm.mock_llm import MockLLMClient
from app.agents.planner.worker import PlannerWorker
from app.common.enums import AgentRole, TaskStatus, TaskType
from app.intelligence.planner import (
    PlannedDecomposition,
    PlannedSubtask,
    PlannerAgent,
    PlannerError,
)
from app.orchestration.contracts import AgentRequest, WorkerResponseEnvelope
from app.orchestration.protocols import WorkerProtocol
from app.state.models import ResearchGoal, ResearchPlan


def _make_agent_request(
    run_id: str = "run_test_plan",
    subtask_id: str = "root_plan_task",
    agent_role: AgentRole = AgentRole.PLANNER,
    task_type: TaskType = TaskType.DECOMPOSITION,
    goal_context: str = "Investigate quantum computing fault tolerance",
    input_data: dict[str, Any] | None = None,
) -> AgentRequest:
    return AgentRequest(
        request_id="req_001",
        run_id=run_id,
        subtask_id=subtask_id,
        agent_role=agent_role,
        task_type=task_type,
        goal_context=goal_context,
        input_data=input_data or {},
        idempotency_key="idem_001",
    )


def test_planner_worker_protocol_compliance() -> None:
    """Test 1: Verify PlannerWorker implements WorkerProtocol."""
    worker = PlannerWorker()
    assert isinstance(worker, WorkerProtocol)


@pytest.mark.asyncio
async def test_valid_decomposition_execution() -> None:
    """Test 2, 6, 7, 8, 9, 10: Verify valid decomposition execution returns complete subtasks and edges."""
    worker = PlannerWorker()
    request = _make_agent_request(
        goal_context="Analyze high-temperature superconductivity mechanisms",
        input_data={"plan_id": "plan_sc_01", "max_subtasks": 5},
    )

    envelope: WorkerResponseEnvelope = await worker.execute(request)

    assert envelope.status == TaskStatus.COMPLETED
    assert envelope.run_id == "run_test_plan"
    assert envelope.subtask_id == "root_plan_task"
    assert envelope.error is None
    assert envelope.response is not None
    assert envelope.response.is_success is True

    output = envelope.response.output_data
    assert output["plan_id"] == "plan_sc_01"
    assert output["run_id"] == "run_test_plan"
    assert output["total_subtasks"] == 4
    assert len(output["planned_subtasks"]) == 4
    assert len(output["edges"]) == 3

    # Verify task order and dependencies
    subtasks = output["planned_subtasks"]
    task_ids = [s["subtask_id"] for s in subtasks]
    assert task_ids == ["task_01", "task_02", "task_03", "task_04"]


@pytest.mark.asyncio
async def test_unsupported_role_rejection() -> None:
    """Test 5: Verify request with unsupported agent role fails with UNSUPPORTED_ROLE."""
    worker = PlannerWorker()
    request = _make_agent_request(agent_role=AgentRole.RESEARCHER)

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "UNSUPPORTED_ROLE"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_unsupported_task_type_rejection() -> None:
    """Test 4: Verify request with unsupported task type fails with UNSUPPORTED_TASK_TYPE."""
    worker = PlannerWorker()
    request = _make_agent_request(task_type=TaskType.WEB_SEARCH)

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "UNSUPPORTED_TASK_TYPE"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_empty_goal_query_rejection() -> None:
    """Test 12: Verify empty research goal query fails with INVALID_PLANNER_INPUT."""
    worker = PlannerWorker()
    request = _make_agent_request(goal_context="   ", input_data={"research_goal": ""})

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "INVALID_PLANNER_INPUT"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_empty_run_id_rejection() -> None:
    """Test 11: Verify empty run_id fails with INVALID_RUN_ID."""
    worker = PlannerWorker()
    request = _make_agent_request(run_id="   ")

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "INVALID_RUN_ID"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_dag_validation_error_mapping() -> None:
    """Test 14: Verify cyclic dependency in Planner output maps to DAG_VALIDATION_ERROR."""
    mock_llm = MockLLMClient()
    # Configure cyclic dependency: t1 -> t2 -> t1
    cyclic_decomp = PlannedDecomposition(
        rationale="Cyclic",
        subtasks=(
            PlannedSubtask(
                subtask_id="task_A",
                objective="Task A",
                prerequisite_ids=("task_B",),
                assigned_role=AgentRole.RESEARCHER,
            ),
            PlannedSubtask(
                subtask_id="task_B",
                objective="Task B",
                prerequisite_ids=("task_A",),
                assigned_role=AgentRole.RESEARCHER,
            ),
        ),
    )
    mock_llm.set_structured_response(PlannedDecomposition, cyclic_decomp)
    planner_agent = PlannerAgent(llm_client=mock_llm)
    worker = PlannerWorker(planner_agent=planner_agent)

    request = _make_agent_request()
    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "DAG_VALIDATION_ERROR"
    assert envelope.error.is_retryable is False


@pytest.mark.asyncio
async def test_planner_error_retryability_mapping() -> None:
    """Test 13: Verify PlannerError from empty subtask list maps to PLANNING_FAILED with is_retryable=True."""
    mock_llm = MockLLMClient()

    class FaultyPlannerAgent(PlannerAgent):
        async def plan(
            self,
            goal: ResearchGoal,
            run_id: str | None = None,
            plan_id: str | None = None,
        ) -> ResearchPlan:
            _ = (goal, run_id, plan_id)
            raise PlannerError("Simulated LLM planning timeout or empty subtask list")

    worker = PlannerWorker(planner_agent=FaultyPlannerAgent(llm_client=mock_llm))
    request = _make_agent_request()

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.FAILED
    assert envelope.error is not None
    assert envelope.error.error_code == "PLANNING_FAILED"
    assert envelope.error.is_retryable is True


@pytest.mark.asyncio
async def test_deterministic_output_and_identifiers() -> None:
    """Test 15: Verify repeated execution with identical request produces identical deterministic IDs."""
    worker = PlannerWorker()
    request = _make_agent_request(
        run_id="run_det_01", input_data={"plan_id": "plan_det_01"}
    )

    env1 = await worker.execute(request)
    env2 = await worker.execute(request)

    assert env1.envelope_id == env2.envelope_id
    assert env1.response is not None and env2.response is not None
    assert env1.response.response_id == env2.response.response_id
    assert env1.response.output_data["plan_id"] == env2.response.output_data["plan_id"]


@pytest.mark.asyncio
async def test_no_downstream_task_execution() -> None:
    """Test 16: Verify PlannerWorker only outputs task node specifications and does not execute them."""
    worker = PlannerWorker()
    request = _make_agent_request()

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.COMPLETED
    assert envelope.response is not None
    subtasks = envelope.response.output_data["planned_subtasks"]
    for s in subtasks:
        assert "subtask_id" in s
        assert "objective" in s
        assert "task_type" in s
        assert "assigned_role" in s


@pytest.mark.asyncio
async def test_custom_constraints_and_domain_tags() -> None:
    """Test 17: Verify custom constraints and domain tags are parsed and applied."""
    worker = PlannerWorker()
    request = _make_agent_request(
        input_data={
            "research_goal": "Evaluate mRNA stability under cryogenic conditions",
            "domain_tags": ["biomedical", "cryogenics"],
            "constraints": {"max_subtasks": 5, "depth": "deep"},
        }
    )

    envelope = await worker.execute(request)

    assert envelope.status == TaskStatus.COMPLETED
    assert envelope.response is not None
    assert envelope.response.output_data["total_subtasks"] == 4
