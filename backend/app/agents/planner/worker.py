"""PlannerWorker adapter bridging AgentRequest execution to PlannerAgent."""

import time
import uuid
from typing import Any

from app.adapters.llm.mock_llm import MockLLMClient
from app.common.enums import AgentRole, TaskStatus, TaskType
from app.common.errors import DAGValidationError, ResearchMindError
from app.intelligence.planner import (
    PlannedDecomposition,
    PlannedSubtask,
    PlannerAgent,
    PlannerError,
)
from app.orchestration.contracts import (
    AgentError,
    AgentRequest,
    AgentResponse,
    TokenUsage,
    WorkerResponseEnvelope,
)
from app.orchestration.protocols import WorkerProtocol
from app.state.models import ResearchGoal


def _default_mock_planner_agent() -> PlannerAgent:
    """Construct a PlannerAgent backed by MockLLMClient with standard default decomposition."""
    mock_llm = MockLLMClient()
    default_decomp = PlannedDecomposition(
        rationale="Decompose research inquiry into initial search, analysis, and verification subtasks.",
        subtasks=(
            PlannedSubtask(
                subtask_id="task_01",
                task_type=TaskType.WEB_SEARCH,
                objective="Gather primary literature and empirical evidence.",
                search_queries=("primary research literature", "empirical benchmarks"),
                assigned_role=AgentRole.RESEARCHER,
                prerequisite_ids=(),
            ),
            PlannedSubtask(
                subtask_id="task_02",
                task_type=TaskType.SYNTHESIS,
                objective="Synthesize gathered findings and extract factual assertions.",
                search_queries=(),
                assigned_role=AgentRole.ANALYST,
                prerequisite_ids=("task_01",),
            ),
            PlannedSubtask(
                subtask_id="task_03",
                task_type=TaskType.VERIFICATION,
                objective="Cross-examine extracted claims against primary evidence.",
                search_queries=(),
                assigned_role=AgentRole.VERIFIER,
                prerequisite_ids=("task_02",),
            ),
            PlannedSubtask(
                subtask_id="task_04",
                task_type=TaskType.REPORTING,
                objective="Compile publication-ready research dossier.",
                search_queries=(),
                assigned_role=AgentRole.REPORTER,
                prerequisite_ids=("task_03",),
            ),
        ),
    )
    mock_llm.set_structured_response(PlannedDecomposition, default_decomp)
    return PlannerAgent(llm_client=mock_llm)


class PlannerWorker(WorkerProtocol):
    """WorkerProtocol adapter executing TaskType.DECOMPOSITION using PlannerAgent."""

    def __init__(
        self,
        planner_agent: PlannerAgent | None = None,
        worker_id: str = "planner-worker-01",
    ) -> None:
        self.planner_agent = planner_agent or _default_mock_planner_agent()
        self.worker_id = worker_id

    async def execute(self, request: AgentRequest) -> WorkerResponseEnvelope:
        """Execute goal decomposition and return structured subtasks in WorkerResponseEnvelope."""
        # 1. Validate run_id
        if not request.run_id or not request.run_id.strip():
            err = AgentError(
                error_code="INVALID_RUN_ID",
                error_type="EvidenceValidationError",
                message="run_id must not be empty or whitespace only",
                is_retryable=False,
            )
            return self._build_error_envelope(request, err)

        clean_run_id = request.run_id.strip()

        # 2. Validate agent role
        if request.agent_role != AgentRole.PLANNER:
            err = AgentError(
                error_code="UNSUPPORTED_ROLE",
                error_type="ValueError",
                message=f"PlannerWorker expects AgentRole.PLANNER, got '{request.agent_role}'",
                is_retryable=False,
            )
            return self._build_error_envelope(request, err)

        # 3. Validate task type
        if request.task_type != TaskType.DECOMPOSITION:
            err = AgentError(
                error_code="UNSUPPORTED_TASK_TYPE",
                error_type="ValueError",
                message=f"PlannerWorker expects TaskType.DECOMPOSITION, got '{request.task_type}'",
                is_retryable=False,
            )
            return self._build_error_envelope(request, err)

        # 4. Extract and validate research goal query
        goal_query = request.input_data.get("research_goal") or request.goal_context
        if not goal_query or not isinstance(goal_query, str) or not goal_query.strip():
            err = AgentError(
                error_code="INVALID_PLANNER_INPUT",
                error_type="ValueError",
                message="Research goal query must not be empty or whitespace only",
                is_retryable=False,
            )
            return self._build_error_envelope(request, err)

        # 5. Extract optional constraints & limits
        constraints = request.input_data.get("constraints", {})
        if not isinstance(constraints, dict):
            constraints = {}

        max_subtasks = request.input_data.get("max_subtasks") or constraints.get(
            "max_subtasks", 10
        )
        try:
            max_subtasks_int = max(1, min(50, int(max_subtasks)))
        except (ValueError, TypeError):
            max_subtasks_int = 10

        domain_tags = request.input_data.get("domain_tags") or constraints.get(
            "domains_allowed", ()
        )
        if isinstance(domain_tags, list):
            domain_tags = tuple(domain_tags)
        elif not isinstance(domain_tags, tuple):
            domain_tags = ()

        goal_id = request.input_data.get("goal_id", f"goal_{uuid.uuid4().hex[:8]}")
        plan_id = request.input_data.get("plan_id")

        goal = ResearchGoal(
            goal_id=goal_id,
            query=goal_query.strip(),
            max_subtasks=max_subtasks_int,
            domain_tags=domain_tags,
            constraints=constraints,
        )

        start_time = time.perf_counter()

        # 6. Delegate planning to PlannerAgent
        try:
            plan = await self.planner_agent.plan(
                goal=goal,
                run_id=clean_run_id,
                plan_id=plan_id,
            )
        except DAGValidationError as e:
            err = AgentError(
                error_code="DAG_VALIDATION_ERROR",
                error_type="DAGValidationError",
                message=str(e),
                is_retryable=False,
            )
            return self._build_error_envelope(request, err)
        except PlannerError as e:
            err = AgentError(
                error_code="PLANNING_FAILED",
                error_type="PlannerError",
                message=str(e),
                is_retryable=True,
            )
            return self._build_error_envelope(request, err)
        except ResearchMindError as e:
            err = AgentError(
                error_code="RESEARCH_MIND_ERROR",
                error_type=type(e).__name__,
                message=str(e),
                is_retryable=False,
            )
            return self._build_error_envelope(request, err)
        except Exception as e:
            err = AgentError(
                error_code="UNEXPECTED_PLANNER_ERROR",
                error_type=type(e).__name__,
                message=str(e),
                is_retryable=True,
            )
            return self._build_error_envelope(request, err)

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        # 7. Serialize plan output data
        serialized_subtasks = [node.model_dump() for node in plan.nodes.values()]
        serialized_edges = [edge.model_dump() for edge in plan.edges]

        output_data: dict[str, Any] = {
            "plan_id": plan.plan_id,
            "run_id": clean_run_id,
            "planned_subtasks": serialized_subtasks,
            "edges": serialized_edges,
            "total_subtasks": len(plan.nodes),
            "rationale": plan.metadata.notes or "",
        }

        # Deterministic IDs
        response_id = f"resp_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{clean_run_id}:{request.request_id}').hex[:12]}"
        envelope_id = f"env_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{clean_run_id}:{request.request_id}').hex[:12]}"

        agent_response = AgentResponse(
            response_id=response_id,
            request_id=request.request_id,
            run_id=clean_run_id,
            subtask_id=request.subtask_id,
            agent_role=AgentRole.PLANNER,
            output_data=output_data,
            execution_time_ms=duration_ms,
            token_usage=TokenUsage(
                prompt_tokens=40, completion_tokens=120, total_tokens=160
            ),
            error=None,
        )

        return WorkerResponseEnvelope(
            envelope_id=envelope_id,
            dispatch_id=f"disp_{request.request_id}",
            run_id=clean_run_id,
            subtask_id=request.subtask_id,
            status=TaskStatus.COMPLETED,
            response=agent_response,
            error=None,
            worker_id=self.worker_id,
        )

    def _build_error_envelope(
        self, request: AgentRequest, error: AgentError
    ) -> WorkerResponseEnvelope:
        """Construct a standardized failure WorkerResponseEnvelope."""
        run_id = (
            request.run_id
            if request.run_id and request.run_id.strip()
            else "unknown_run"
        )
        envelope_id = f"env_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{run_id}:{request.request_id}').hex[:12]}"
        response_id = f"resp_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{run_id}:{request.request_id}').hex[:12]}"

        agent_response = AgentResponse(
            response_id=response_id,
            request_id=request.request_id,
            run_id=run_id,
            subtask_id=request.subtask_id,
            agent_role=request.agent_role,
            output_data={},
            execution_time_ms=0,
            token_usage=TokenUsage(),
            error=error,
        )

        return WorkerResponseEnvelope(
            envelope_id=envelope_id,
            dispatch_id=f"disp_{request.request_id}",
            run_id=run_id,
            subtask_id=request.subtask_id,
            status=TaskStatus.FAILED,
            response=agent_response,
            error=error,
            worker_id=self.worker_id,
        )


__all__ = ["PlannerWorker"]
