"""Research service orchestrating asynchronous background runs and event streams."""

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from app.api.schemas import (
    CancelRunResponse,
    CreateRunRequest,
    RunDetailResponse,
    RunSummaryResponse,
)
from app.common.enums import (
    AgentRole,
    EdgeType,
    RunStage,
    TaskStatus,
    TaskType,
)
from app.intelligence.models import ResearchDossier
from app.orchestration.cancellation import CancellationToken
from app.orchestration.contracts import AgentRequest, TokenUsage, WorkerResponseEnvelope
from app.orchestration.events import ExecutionEvent
from app.orchestration.executor import DAGExecutor, ExecutionResult
from app.orchestration.protocols import (
    CheckpointRepositoryProtocol,
    WorkerProtocol,
)
from app.orchestration.router import (
    create_default_worker_router,
)
from app.orchestration.runtime import (
    InMemoryCheckpointRepository,
    InMemoryEventSink,
)
from app.state.models import (
    DependencyEdge,
    ResearchGoal,
    ResearchPlan,
    SubtaskNode,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class RunContext:
    """Runtime execution container for an active or completed research run."""

    def __init__(
        self,
        run_id: str,
        goal: ResearchGoal,
        cancellation_token: CancellationToken,
        event_sink: InMemoryEventSink,
        checkpoint_repo: CheckpointRepositoryProtocol,
    ) -> None:
        self.run_id = run_id
        self.goal = goal
        self.cancellation_token = cancellation_token
        self.event_sink = event_sink
        self.checkpoint_repo = checkpoint_repo
        self.created_at: datetime = _utc_now()
        self.start_time: float = time.monotonic()
        self.status: RunStage = RunStage.QUEUED
        self.plan_id: str | None = None
        self.completed_task_ids: list[str] = []
        self.failed_task_ids: list[str] = []
        self.cancelled_task_ids: list[str] = []
        self.total_token_usage: TokenUsage = TokenUsage()
        self.duration_seconds: float = 0.0
        self.dossier: ResearchDossier | None = None
        self.error: str | None = None
        self.task_future: asyncio.Task[None] | None = None


class ResearchService:
    """Service layer managing research run lifecycles, background coordination, and SSE telemetry."""

    def __init__(
        self,
        router: WorkerProtocol | None = None,
        max_concurrency: int = 4,
    ) -> None:
        self._router = router or create_default_worker_router()
        self._max_concurrency = max_concurrency
        self._runs: dict[str, RunContext] = {}
        self._lock = asyncio.Lock()

    async def create_and_start_run(
        self, request: CreateRunRequest
    ) -> RunSummaryResponse:
        """Initialize research run, register cancellation token, and spawn background execution task."""
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        goal_id = f"goal_{uuid.uuid4().hex[:8]}"

        goal = ResearchGoal(
            goal_id=goal_id,
            query=request.query,
            domain_tags=request.domain_tags,
            constraints=request.constraints,
            max_subtasks=request.max_subtasks,
        )

        event_sink = InMemoryEventSink()
        checkpoint_repo = InMemoryCheckpointRepository()
        token = CancellationToken()

        context = RunContext(
            run_id=run_id,
            goal=goal,
            cancellation_token=token,
            event_sink=event_sink,
            checkpoint_repo=checkpoint_repo,
        )

        async with self._lock:
            self._runs[run_id] = context

        # Spawn background orchestration task
        task = asyncio.create_task(self._execute_run_pipeline(context))
        context.task_future = task

        return RunSummaryResponse(
            run_id=run_id,
            goal_query=goal.query,
            status=context.status,
            created_at=context.created_at,
            duration_seconds=0.0,
        )

    async def get_run(self, run_id: str) -> RunDetailResponse | None:
        """Fetch detailed status, token usage, and compiled ResearchDossier for a run ID."""
        context = self._runs.get(run_id)
        if not context:
            return None

        # Compute live duration if still running
        if context.status in (
            RunStage.QUEUED,
            RunStage.PLANNING,
            RunStage.RESEARCHING,
            RunStage.ANALYZING,
            RunStage.VERIFYING,
            RunStage.EVALUATING,
            RunStage.REPORTING,
        ):
            duration = time.monotonic() - context.start_time
        else:
            duration = context.duration_seconds

        return RunDetailResponse(
            run_id=context.run_id,
            plan_id=context.plan_id,
            goal_query=context.goal.query,
            status=context.status,
            completed_task_ids=tuple(context.completed_task_ids),
            failed_task_ids=tuple(context.failed_task_ids),
            cancelled_task_ids=tuple(context.cancelled_task_ids),
            total_token_usage=context.total_token_usage,
            duration_seconds=duration,
            dossier=context.dossier,
            error=context.error,
            created_at=context.created_at,
        )

    async def cancel_run(self, run_id: str) -> CancelRunResponse:
        """Signal cooperative cancellation for an in-flight research run."""
        context = self._runs.get(run_id)
        if not context:
            raise KeyError(f"Research run '{run_id}' not found")

        context.cancellation_token.cancel(reason="Cancelled by client request")
        context.status = RunStage.CANCELLED
        context.duration_seconds = time.monotonic() - context.start_time

        return CancelRunResponse(
            run_id=run_id,
            status=RunStage.CANCELLED,
            message="Cancellation requested successfully",
        )

    async def stream_events(self, run_id: str) -> AsyncIterator[dict[str, Any]]:
        """Yield Server-Sent Events (SSE) detailing real-time run progress and task transitions."""
        context = self._runs.get(run_id)
        if not context:
            raise KeyError(f"Research run '{run_id}' not found")

        last_index = 0
        while True:
            events: list[ExecutionEvent] = context.event_sink.get_events(run_id)
            while last_index < len(events):
                event = events[last_index]
                last_index += 1
                yield {
                    "event": event.__class__.__name__,
                    "data": (
                        event.model_dump_json()
                        if hasattr(event, "model_dump_json")
                        else str(event)
                    ),
                }

            if context.status in (
                RunStage.COMPLETED,
                RunStage.FAILED,
                RunStage.CANCELLED,
            ) and last_index >= len(events):
                break

            await asyncio.sleep(0.1)

    async def _execute_run_pipeline(self, context: RunContext) -> None:
        """Coordinate full Planner -> DAGExecutor -> AgentWorkerRouter pipeline in background."""
        context.status = RunStage.PLANNING
        run_id = context.run_id
        goal_query = context.goal.query

        try:
            # 1. PlannerWorker Decomposes the Goal
            planner_req = AgentRequest(
                request_id=f"req_plan_{run_id}",
                run_id=run_id,
                subtask_id="planner_task",
                agent_role=AgentRole.PLANNER,
                task_type=TaskType.DECOMPOSITION,
                goal_context=goal_query,
                input_data={"goal_query": goal_query},
                idempotency_key=f"idem_plan_{run_id}",
            )

            planner_env: WorkerResponseEnvelope = await self._router.execute(
                planner_req
            )

            if planner_env.status != TaskStatus.COMPLETED or not planner_env.response:
                context.status = RunStage.FAILED
                context.error = (
                    planner_env.error.message
                    if planner_env.error
                    else "Planning phase failed"
                )
                context.duration_seconds = time.monotonic() - context.start_time
                return

            planned_subtasks = planner_env.response.output_data.get(
                "planned_subtasks", []
            )
            raw_edges = planner_env.response.output_data.get("edges", [])
            plan_id = planner_env.response.output_data.get("plan_id", f"plan_{run_id}")
            context.plan_id = plan_id

            # 2. Build SubtaskNodes and DependencyEdges from decomposition
            nodes: dict[str, SubtaskNode] = {}
            for st in planned_subtasks:
                if isinstance(st, dict):
                    node = SubtaskNode.model_validate(st)
                elif isinstance(st, SubtaskNode):
                    node = st
                else:
                    continue
                nodes[node.subtask_id] = node

            edges_list: list[DependencyEdge] = [
                DependencyEdge.model_validate(e) if isinstance(e, dict) else e
                for e in raw_edges
            ]

            # Ensure downstream synthesis -> verification -> evaluation -> reporting chain if not present
            self._ensure_complete_research_mesh(nodes, edges_list, goal_query)

            plan = ResearchPlan(
                plan_id=plan_id,
                run_id=run_id,
                goal=context.goal,
                nodes=nodes,
                edges=tuple(edges_list),
            )

            # 3. Execute Research DAG with DAGExecutor and AgentWorkerRouter
            context.status = RunStage.RESEARCHING
            executor = DAGExecutor(
                max_concurrency=self._max_concurrency,
                worker_registry=self._router,
                checkpoint_repo=context.checkpoint_repo,
                event_sink=context.event_sink,
            )

            result: ExecutionResult = await executor.execute_plan(
                plan=plan, cancellation_token=context.cancellation_token
            )

            # 4. Record Results
            context.status = result.status
            context.completed_task_ids = list(result.completed_task_ids)
            context.failed_task_ids = list(result.failed_task_ids)
            context.cancelled_task_ids = list(result.cancelled_task_ids)
            context.total_token_usage = result.total_token_usage
            context.duration_seconds = time.monotonic() - context.start_time
            context.error = result.error

            # 5. Extract final ResearchDossier if available
            for task_id in reversed(result.completed_task_ids):
                output = result.task_outputs.get(task_id, {})
                if (
                    isinstance(output, dict)
                    and "dossier_id" in output
                    and "markdown_report" in output
                ):
                    context.dossier = ResearchDossier.model_validate(output)
                    break

        except Exception as e:
            context.status = RunStage.FAILED
            context.error = str(e)
            context.duration_seconds = time.monotonic() - context.start_time

    def _resolve_role_for_task(self, task_type: TaskType) -> AgentRole:
        """Map TaskType to the canonical responsible AgentRole."""
        if task_type == TaskType.DECOMPOSITION:
            return AgentRole.PLANNER
        if task_type in (
            TaskType.WEB_SEARCH,
            TaskType.ACADEMIC_SEARCH,
            TaskType.DOC_ANALYSIS,
        ):
            return AgentRole.RESEARCHER
        if task_type == TaskType.SYNTHESIS:
            return AgentRole.ANALYST
        if task_type in (TaskType.VERIFICATION, TaskType.CONFLICT_DETECTION):
            return AgentRole.VERIFIER
        if task_type == TaskType.EVALUATION:
            return AgentRole.EVALUATOR
        if task_type == TaskType.REPORTING:
            return AgentRole.REPORTER
        return AgentRole.RESEARCHER

    def _ensure_complete_research_mesh(
        self,
        nodes: dict[str, SubtaskNode],
        edges: list[DependencyEdge],
        goal_query: str,
    ) -> None:
        """Guarantee the DAG includes synthesis, verification, evaluation, and reporting nodes."""
        research_ids = [
            nid
            for nid, n in nodes.items()
            if n.task_type
            in (
                TaskType.WEB_SEARCH,
                TaskType.ACADEMIC_SEARCH,
                TaskType.DOC_ANALYSIS,
            )
        ]

        if not any(n.task_type == TaskType.SYNTHESIS for n in nodes.values()):
            an_id = "task_an_auto"
            nodes[an_id] = SubtaskNode(
                subtask_id=an_id,
                task_type=TaskType.SYNTHESIS,
                objective="Synthesize factual claims from evidence",
                assigned_role=AgentRole.ANALYST,
            )
            for rid in research_ids:
                edges.append(
                    DependencyEdge(
                        source_id=rid, target_id=an_id, edge_type=EdgeType.DATA
                    )
                )

        an_ids = [nid for nid, n in nodes.items() if n.task_type == TaskType.SYNTHESIS]

        if not any(n.task_type == TaskType.VERIFICATION for n in nodes.values()):
            ver_id = "task_ver_auto"
            nodes[ver_id] = SubtaskNode(
                subtask_id=ver_id,
                task_type=TaskType.VERIFICATION,
                objective="Verify claims and grounding",
                assigned_role=AgentRole.VERIFIER,
            )
            for rid in research_ids:
                edges.append(
                    DependencyEdge(
                        source_id=rid, target_id=ver_id, edge_type=EdgeType.DATA
                    )
                )
            for aid in an_ids:
                edges.append(
                    DependencyEdge(
                        source_id=aid, target_id=ver_id, edge_type=EdgeType.DATA
                    )
                )

        ver_ids = [
            nid for nid, n in nodes.items() if n.task_type == TaskType.VERIFICATION
        ]

        if not any(n.task_type == TaskType.EVALUATION for n in nodes.values()):
            eval_id = "task_eval_auto"
            nodes[eval_id] = SubtaskNode(
                subtask_id=eval_id,
                task_type=TaskType.EVALUATION,
                objective="Evaluate research synthesis quality",
                assigned_role=AgentRole.EVALUATOR,
                input_context={"goal_query": goal_query},
            )
            for aid in an_ids:
                edges.append(
                    DependencyEdge(
                        source_id=aid,
                        target_id=eval_id,
                        edge_type=EdgeType.DATA,
                    )
                )
            for vid in ver_ids:
                edges.append(
                    DependencyEdge(
                        source_id=vid,
                        target_id=eval_id,
                        edge_type=EdgeType.DATA,
                    )
                )

        eval_ids = [
            nid for nid, n in nodes.items() if n.task_type == TaskType.EVALUATION
        ]

        if not any(n.task_type == TaskType.REPORTING for n in nodes.values()):
            rep_id = "task_rep_auto"
            nodes[rep_id] = SubtaskNode(
                subtask_id=rep_id,
                task_type=TaskType.REPORTING,
                objective="Compile publication-ready ResearchDossier",
                assigned_role=AgentRole.REPORTER,
                input_context={"goal_query": goal_query},
            )
            for aid in an_ids:
                edges.append(
                    DependencyEdge(
                        source_id=aid, target_id=rep_id, edge_type=EdgeType.DATA
                    )
                )
            for vid in ver_ids:
                edges.append(
                    DependencyEdge(
                        source_id=vid, target_id=rep_id, edge_type=EdgeType.DATA
                    )
                )
            for eid in eval_ids:
                edges.append(
                    DependencyEdge(
                        source_id=eid, target_id=rep_id, edge_type=EdgeType.DATA
                    )
                )


__all__ = ["ResearchService", "RunContext"]
