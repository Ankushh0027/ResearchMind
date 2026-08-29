"""Job worker gateway coordinating Planner and DAGExecutor through AgentWorkerRouter."""

import time
from typing import Any

from app.common.enums import (
    AgentRole,
    EdgeType,
    RunStage,
    TaskStatus,
    TaskType,
)
from app.config.settings import get_settings
from app.intelligence.models import EvaluationReport, ResearchDossier
from app.jobs.protocols import (
    JobEnvelope,
    JobHandlerProtocol,
    JobStatus,
    RunContextResolver,
)
from app.observability.factory import get_metrics, get_tracer
from app.observability.metrics import ObservabilityBridgeHook
from app.orchestration.cancellation import CancellationToken
from app.orchestration.contracts import AgentRequest, WorkerResponseEnvelope
from app.orchestration.executor import DAGExecutor, ExecutionResult
from app.orchestration.protocols import CheckpointRepositoryProtocol, WorkerProtocol
from app.orchestration.refinement import RefinementPlanner
from app.orchestration.router import create_default_worker_router
from app.orchestration.runtime import (
    InMemoryCheckpointRepository,
    InMemoryEventSink,
)
from app.persistence.protocols import (
    RunContext,
    RunRepositoryProtocol,
)
from app.state.models import (
    DependencyEdge,
    ResearchPlan,
    SubtaskNode,
)
from app.storage.models import ArtifactType
from app.storage.protocols import ArtifactStorageProtocol


class ResearchJobWorker(JobHandlerProtocol):
    """Worker gateway receiving JobEnvelopes and executing the multi-agent research workflow."""

    def __init__(
        self,
        router: WorkerProtocol | None = None,
        run_context_resolver: RunContextResolver | None = None,
        run_repo: RunRepositoryProtocol | None = None,
        checkpoint_repo: CheckpointRepositoryProtocol | None = None,
        artifact_storage: ArtifactStorageProtocol | None = None,
        max_concurrency: int = 4,
    ) -> None:
        self._router = router or create_default_worker_router()
        self._resolver = run_context_resolver
        self._run_repo = run_repo
        self._checkpoint_repo = checkpoint_repo
        self._artifact_storage = artifact_storage
        self._max_concurrency = max_concurrency

    def set_run_context_resolver(self, resolver: RunContextResolver) -> None:
        """Configure or update the run context lookup function."""
        self._resolver = resolver

    def set_run_repository(self, repo: RunRepositoryProtocol) -> None:
        """Configure or update the durable RunRepository."""
        self._run_repo = repo

    def set_checkpoint_repository(self, repo: CheckpointRepositoryProtocol) -> None:
        """Configure or update the CheckpointRepository."""
        self._checkpoint_repo = repo

    def set_artifact_storage(self, storage: ArtifactStorageProtocol) -> None:
        """Configure or update the ArtifactStorage backend."""
        self._artifact_storage = storage

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
        context = self._resolver(run_id) if self._resolver is not None else None

        if context is None and self._run_repo is not None:
            record = await self._run_repo.get_run(run_id)
            if record is not None:
                token = CancellationToken()
                if record.is_cancelled:
                    token.cancel(record.cancellation_reason or "Cancelled")
                context = RunContext(
                    run_id=record.run_id,
                    goal=record.goal,
                    cancellation_token=token,
                    event_sink=InMemoryEventSink(),
                    checkpoint_repo=self._checkpoint_repo
                    or InMemoryCheckpointRepository(),
                )
                context.status = record.status
                context.plan_id = record.plan_id
                context.completed_task_ids = list(record.completed_task_ids)
                context.failed_task_ids = list(record.failed_task_ids)
                context.cancelled_task_ids = list(record.cancelled_task_ids)
                context.total_token_usage = record.total_token_usage
                context.duration_seconds = record.duration_seconds
                context.dossier = record.dossier
                context.artifacts = list(record.artifacts)
                context.error = record.error

        if context is None:
            return envelope.with_status(
                JobStatus.FAILED,
                error=f"RunContext not found for run_id '{run_id}'",
                is_retryable=False,
            )

        async def _sync_to_repo() -> None:
            if self._run_repo is not None and context is not None:
                existing = await self._run_repo.get_run(run_id)
                if existing is not None:
                    await self._run_repo.update_run(
                        existing.with_updates(
                            status=context.status,
                            plan_id=context.plan_id,
                            completed_task_ids=context.completed_task_ids,
                            failed_task_ids=context.failed_task_ids,
                            cancelled_task_ids=context.cancelled_task_ids,
                            total_token_usage=context.total_token_usage,
                            duration_seconds=context.duration_seconds,
                            dossier=context.dossier,
                            artifacts=context.artifacts,
                            error=context.error,
                            is_cancelled=context.cancellation_token.is_cancelled,
                        )
                    )

        # 3. Check for already completed or cancelled run (Idempotent At-Least-Once Delivery Protection)
        if context.status == RunStage.COMPLETED:
            return envelope.with_status(JobStatus.COMPLETED)

        if (
            context.status == RunStage.CANCELLED
            or context.cancellation_token.is_cancelled
        ):
            context.status = RunStage.CANCELLED
            context.duration_seconds = time.monotonic() - context.start_time
            await _sync_to_repo()
            return envelope.with_status(JobStatus.CANCELLED)

        context.status = RunStage.PLANNING
        await _sync_to_repo()

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
                await _sync_to_repo()
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
                await _sync_to_repo()
                return envelope.with_status(JobStatus.CANCELLED)

            # 7. Execute DAG with DAGExecutor and AgentWorkerRouter
            context.status = RunStage.RESEARCHING
            await _sync_to_repo()

            tracer = get_tracer()
            metrics = get_metrics()

            executor = DAGExecutor(
                max_concurrency=self._max_concurrency,
                worker_registry=self._router,
                checkpoint_repo=context.checkpoint_repo,
                event_sink=context.event_sink,
                observability_hook=ObservabilityBridgeHook(
                    tracer=tracer, metrics=metrics
                ),
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
                await _sync_to_repo()
                return envelope.with_status(JobStatus.CANCELLED)

            if result.status == RunStage.COMPLETED:
                # ------------------------------------------------------------------
                # Phase 6.9: Autonomous Self-Correction & Refinement Loop
                # ------------------------------------------------------------------
                settings = get_settings()
                max_refinement_loops = settings.max_refinement_loops
                refinement_enabled = settings.refinement_enabled

                eval_report = self._extract_eval_report(result.task_outputs)
                iteration = 0
                all_task_outputs = dict(result.task_outputs)

                while (
                    refinement_enabled
                    and eval_report is not None
                    and (not eval_report.passed or eval_report.overall_score < 0.85)
                    and iteration < max_refinement_loops
                ):
                    if context.cancellation_token.is_cancelled:
                        context.status = RunStage.CANCELLED
                        context.duration_seconds = time.monotonic() - context.start_time
                        await _sync_to_repo()
                        return envelope.with_status(JobStatus.CANCELLED)

                    iteration += 1
                    self._record_refinement_telemetry(
                        run_id, iteration, eval_report.overall_score, "started"
                    )

                    refinement_plan_wrapper = RefinementPlanner.create_refinement_plan(
                        eval_report=eval_report,
                        iteration=iteration,
                        run_id=run_id,
                        goal=context.goal,
                    )

                    if context.cancellation_token.is_cancelled:
                        context.status = RunStage.CANCELLED
                        context.duration_seconds = time.monotonic() - context.start_time
                        await _sync_to_repo()
                        return envelope.with_status(JobStatus.CANCELLED)

                    context.status = RunStage.RESEARCHING
                    await _sync_to_repo()

                    refine_result: ExecutionResult = await executor.execute_plan(
                        plan=refinement_plan_wrapper.research_plan,
                        cancellation_token=context.cancellation_token,
                    )

                    context.completed_task_ids.extend(refine_result.completed_task_ids)
                    context.failed_task_ids.extend(refine_result.failed_task_ids)
                    context.total_token_usage = (
                        context.total_token_usage + refine_result.total_token_usage
                    )
                    context.duration_seconds = time.monotonic() - context.start_time

                    if refine_result.status == RunStage.CANCELLED:
                        context.status = RunStage.CANCELLED
                        await _sync_to_repo()
                        return envelope.with_status(JobStatus.CANCELLED)

                    if refine_result.status != RunStage.COMPLETED:
                        # Refinement execution failed
                        break

                    all_task_outputs.update(refine_result.task_outputs)

                    new_eval_report = self._extract_eval_report(
                        refine_result.task_outputs
                    )
                    if new_eval_report is not None:
                        self._record_refinement_telemetry(
                            run_id,
                            iteration,
                            new_eval_report.overall_score,
                            "completed",
                        )
                        eval_report = new_eval_report
                    else:
                        break

                # If refinement ran, re-invoke ReporterWorker to compile final updated dossier
                if iteration > 0:
                    rep_req = AgentRequest(
                        request_id=f"req_rep_final_{run_id}_iter{iteration}",
                        run_id=run_id,
                        subtask_id="task_rep_final",
                        agent_role=AgentRole.REPORTER,
                        task_type=TaskType.REPORTING,
                        goal_context=goal_query,
                        input_data={
                            "goal_query": goal_query,
                            "findings": self._extract_all_findings(all_task_outputs),
                            "claims": self._extract_all_claims(all_task_outputs),
                            "citations": self._extract_all_citations(all_task_outputs),
                            "contradictions": self._extract_all_contradictions(
                                all_task_outputs
                            ),
                            "evaluation": (
                                eval_report.model_dump() if eval_report else None
                            ),
                        },
                        idempotency_key=f"idem_rep_final_{run_id}_iter{iteration}",
                    )
                    rep_env = await self._router.execute(rep_req)
                    if (
                        rep_env.status == TaskStatus.COMPLETED
                        and rep_env.response
                        and rep_env.response.output_data
                    ):
                        context.dossier = ResearchDossier.model_validate(
                            rep_env.response.output_data
                        )
                else:
                    # Extract initial ResearchDossier
                    for task_id in reversed(result.completed_task_ids):
                        output = result.task_outputs.get(task_id, {})
                        if (
                            isinstance(output, dict)
                            and "dossier_id" in output
                            and "markdown_report" in output
                        ):
                            context.dossier = ResearchDossier.model_validate(output)
                            break

                # Persist durable artifacts if storage provider is available
                if context.dossier is not None and self._artifact_storage is not None:
                    try:
                        report_meta = await self._artifact_storage.upload(
                            run_id=run_id,
                            artifact_type=ArtifactType.REPORT_MARKDOWN,
                            content=context.dossier.markdown_report,
                            filename="report.md",
                            content_type="text/markdown",
                            metadata={
                                "dossier_id": context.dossier.dossier_id,
                                "confidence_rating": context.dossier.confidence_rating,
                            },
                        )
                        context.artifacts.append(report_meta)

                        dossier_meta = await self._artifact_storage.upload(
                            run_id=run_id,
                            artifact_type=ArtifactType.DOSSIER_JSON,
                            content=context.dossier.model_dump_json(),
                            filename="dossier.json",
                            content_type="application/json",
                            metadata={
                                "dossier_id": context.dossier.dossier_id,
                            },
                        )
                        context.artifacts.append(dossier_meta)
                    except Exception as upload_err:
                        import logging

                        logging.getLogger("researchmind.worker").warning(
                            "Failed to store durable artifacts for run '%s': %s",
                            run_id,
                            upload_err,
                        )

                context.status = RunStage.COMPLETED
                await _sync_to_repo()
                return envelope.with_status(JobStatus.COMPLETED)

            # Execution resulted in FAILED stage
            await _sync_to_repo()
            return envelope.with_status(
                JobStatus.FAILED,
                error=result.error or "DAG execution failed",
                is_retryable=True,
            )

        except Exception as e:
            context.status = RunStage.FAILED
            context.error = str(e)
            context.duration_seconds = time.monotonic() - context.start_time
            await _sync_to_repo()
            return envelope.with_status(
                JobStatus.FAILED, error=str(e), is_retryable=True
            )

    def _extract_eval_report(
        self, task_outputs: dict[str, Any]
    ) -> EvaluationReport | None:
        """Extract latest EvaluationReport from task execution outputs."""
        for output in reversed(list(task_outputs.values())):
            if (
                isinstance(output, dict)
                and "overall_score" in output
                and "passed" in output
                and "completeness_score" in output
            ):
                try:
                    return EvaluationReport.model_validate(output)
                except Exception:
                    continue
            elif isinstance(output, EvaluationReport):
                return output
        return None

    def _extract_all_findings(
        self, task_outputs: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Collect synthesized KeyFinding items from outputs."""
        findings = []
        for output in task_outputs.values():
            if isinstance(output, dict) and "findings" in output:
                raw = output["findings"]
                if isinstance(raw, list):
                    for item in raw:
                        findings.append(
                            item.model_dump() if hasattr(item, "model_dump") else item
                        )
        return findings

    def _extract_all_claims(self, task_outputs: dict[str, Any]) -> list[dict[str, Any]]:
        """Collect synthesized ExtractedClaim items from outputs."""
        claims = []
        for output in task_outputs.values():
            if isinstance(output, dict) and "claims" in output:
                raw = output["claims"]
                if isinstance(raw, list):
                    for item in raw:
                        claims.append(
                            item.model_dump() if hasattr(item, "model_dump") else item
                        )
        return claims

    def _extract_all_citations(
        self, task_outputs: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Collect CitationReference items from outputs."""
        citations = []
        for output in task_outputs.values():
            if isinstance(output, dict) and "citations" in output:
                raw = output["citations"]
                if isinstance(raw, list):
                    for item in raw:
                        citations.append(
                            item.model_dump() if hasattr(item, "model_dump") else item
                        )
        return citations

    def _extract_all_contradictions(
        self, task_outputs: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Collect ContradictionItem items from outputs."""
        contradictions = []
        for output in task_outputs.values():
            if isinstance(output, dict) and "contradictions" in output:
                raw = output["contradictions"]
                if isinstance(raw, list):
                    for item in raw:
                        contradictions.append(
                            item.model_dump() if hasattr(item, "model_dump") else item
                        )
        return contradictions

    def _record_refinement_telemetry(
        self, run_id: str, iteration: int, score: float, event: str
    ) -> None:
        """Record telemetry metrics for refinement cycles without failing on error."""
        import contextlib

        with contextlib.suppress(Exception):
            metrics = get_metrics()
            metrics.increment_counter(
                f"refinement.{event}",
                attributes={"run_id": run_id, "iteration": iteration},
            )
            metrics.record_histogram(
                "refinement.score",
                score,
                attributes={"run_id": run_id, "iteration": iteration},
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
