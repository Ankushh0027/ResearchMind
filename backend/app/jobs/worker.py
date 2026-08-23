"""Job worker gateway coordinating Planner and DAGExecutor through AgentWorkerRouter."""

import time

from app.common.enums import (
    AgentRole,
    EdgeType,
    RunStage,
    TaskStatus,
    TaskType,
)
from app.intelligence.models import ResearchDossier
from app.jobs.protocols import (
    JobEnvelope,
    JobHandlerProtocol,
    JobStatus,
    RunContextResolver,
)
from app.orchestration.contracts import AgentRequest, WorkerResponseEnvelope
from app.orchestration.executor import DAGExecutor, ExecutionResult
from app.orchestration.protocols import WorkerProtocol
from app.orchestration.router import create_default_worker_router
from app.state.models import (
    DependencyEdge,
    ResearchPlan,
    SubtaskNode,
)


class ResearchJobWorker(JobHandlerProtocol):
    """Worker gateway receiving JobEnvelopes and executing the multi-agent research workflow."""

    def __init__(
        self,
        router: WorkerProtocol | None = None,
        run_context_resolver: RunContextResolver | None = None,
        max_concurrency: int = 4,
    ) -> None:
        self._router = router or create_default_worker_router()
        self._resolver = run_context_resolver
        self._max_concurrency = max_concurrency

    def set_run_context_resolver(self, resolver: RunContextResolver) -> None:
        """Configure or update the run context lookup function."""
        self._resolver = resolver

    async def handle_job(self, envelope: JobEnvelope) -> JobEnvelope:
        """Execute goal decomposition and research DAG for a given job envelope."""
        run_id = envelope.run_id
        goal_query = envelope.goal_query

        # 1. Validate envelope payload
        if not run_id or not run_id.strip():
            return envelope.with_status(
                JobStatus.FAILED,
                error="Invalid run_id: cannot be empty or whitespace",
                is_retryable=False,
            )

        if not goal_query or not goal_query.strip() or len(goal_query.strip()) < 3:
            return envelope.with_status(
                JobStatus.FAILED,
                error="Invalid goal_query: must be at least 3 characters",
                is_retryable=False,
            )

        # 2. Resolve RunContext
        if self._resolver is None:
            return envelope.with_status(
                JobStatus.FAILED,
                error="RunContextResolver not configured on worker",
                is_retryable=False,
            )

        context = self._resolver(run_id)
        if context is None:
            return envelope.with_status(
                JobStatus.FAILED,
                error=f"RunContext not found for run_id '{run_id}'",
                is_retryable=False,
            )

        # 3. Check for early cancellation
        if context.cancellation_token.is_cancelled:
            context.status = RunStage.CANCELLED
            context.duration_seconds = time.monotonic() - context.start_time
            return envelope.with_status(JobStatus.CANCELLED)

        context.status = RunStage.PLANNING

        try:
            # 4. PlannerWorker Decomposes the Goal
            planner_req = AgentRequest(
                request_id=f"req_plan_{run_id}",
                run_id=run_id,
                subtask_id="planner_task",
                agent_role=AgentRole.PLANNER,
                task_type=TaskType.DECOMPOSITION,
                goal_context=goal_query,
                input_data={
                    "goal_query": goal_query,
                    "domain_tags": list(envelope.domain_tags),
                    "constraints": envelope.constraints,
                    "max_subtasks": envelope.max_subtasks,
                },
                idempotency_key=f"idem_plan_{run_id}",
            )

            planner_env: WorkerResponseEnvelope = await self._router.execute(
                planner_req
            )

            if planner_env.status != TaskStatus.COMPLETED or not planner_env.response:
                err_msg = (
                    planner_env.error.message
                    if planner_env.error
                    else "Planning phase failed"
                )
                is_ret = planner_env.error.is_retryable if planner_env.error else False
                context.status = RunStage.FAILED
                context.error = err_msg
                context.duration_seconds = time.monotonic() - context.start_time
                return envelope.with_status(
                    JobStatus.FAILED, error=err_msg, is_retryable=is_ret
                )

            # 5. Extract planned nodes and edges
            planned_subtasks = planner_env.response.output_data.get(
                "planned_subtasks", []
            )
            raw_edges = planner_env.response.output_data.get("edges", [])
            plan_id = planner_env.response.output_data.get("plan_id", f"plan_{run_id}")
            context.plan_id = plan_id

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

            # Ensure downstream synthesis -> verification -> evaluation -> reporting chain if absent
            self._ensure_complete_research_mesh(nodes, edges_list, goal_query)

            plan = ResearchPlan(
                plan_id=plan_id,
                run_id=run_id,
                goal=context.goal,
                nodes=nodes,
                edges=tuple(edges_list),
            )

            # 6. Check for cancellation prior to DAG execution
            if context.cancellation_token.is_cancelled:
                context.status = RunStage.CANCELLED
                context.duration_seconds = time.monotonic() - context.start_time
                return envelope.with_status(JobStatus.CANCELLED)

            # 7. Execute DAG with DAGExecutor and AgentWorkerRouter
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

            # 8. Record Results in Context
            context.status = result.status
            context.completed_task_ids = list(result.completed_task_ids)
            context.failed_task_ids = list(result.failed_task_ids)
            context.cancelled_task_ids = list(result.cancelled_task_ids)
            context.total_token_usage = result.total_token_usage
            context.duration_seconds = time.monotonic() - context.start_time
            context.error = result.error

            if result.status == RunStage.CANCELLED:
                return envelope.with_status(JobStatus.CANCELLED)

            if result.status == RunStage.COMPLETED:
                # Extract final ResearchDossier
                for task_id in reversed(result.completed_task_ids):
                    output = result.task_outputs.get(task_id, {})
                    if (
                        isinstance(output, dict)
                        and "dossier_id" in output
                        and "markdown_report" in output
                    ):
                        context.dossier = ResearchDossier.model_validate(output)
                        break

                return envelope.with_status(JobStatus.COMPLETED)

            # Execution resulted in FAILED stage
            return envelope.with_status(
                JobStatus.FAILED,
                error=result.error or "DAG execution failed",
                is_retryable=True,
            )

        except Exception as e:
            context.status = RunStage.FAILED
            context.error = str(e)
            context.duration_seconds = time.monotonic() - context.start_time
            return envelope.with_status(
                JobStatus.FAILED, error=str(e), is_retryable=True
            )

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


__all__ = ["ResearchJobWorker"]
