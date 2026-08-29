"""Integration tests for autonomous self-correction, dynamic inquiry refinement, and bounded retry loops."""

import pytest

from app.common.enums import (
    AgentRole,
    RunStage,
    TaskStatus,
    TaskType,
    VerificationStatus,
)
from app.config.settings import AppSettings
from app.intelligence.models import (
    CitationReference,
    EvaluationReport,
    EvaluationRubricScore,
    KeyFinding,
    ResearchDossier,
)
from app.jobs.protocols import JobEnvelope, JobStatus
from app.jobs.worker import ResearchJobWorker
from app.orchestration.cancellation import CancellationToken
from app.orchestration.contracts import (
    AgentRequest,
    AgentResponse,
    TokenUsage,
    WorkerResponseEnvelope,
)
from app.orchestration.protocols import WorkerProtocol
from app.orchestration.runtime import (
    InMemoryCheckpointRepository,
    InMemoryEventSink,
)
from app.persistence.in_memory import InMemoryRunRepository
from app.persistence.protocols import RunContext
from app.state.models import ResearchGoal, SubtaskNode
from app.storage.factory import create_artifact_storage


def _make_context(
    run_id: str,
    goal_query: str,
    cancellation_token: CancellationToken | None = None,
) -> RunContext:
    return RunContext(
        run_id=run_id,
        goal=ResearchGoal(goal_id=f"goal_{run_id}", query=goal_query),
        cancellation_token=cancellation_token or CancellationToken(),
        event_sink=InMemoryEventSink(),
        checkpoint_repo=InMemoryCheckpointRepository(),
    )


class MockDynamicRefinementRouter(WorkerProtocol):
    """Router that simulates initial evaluation failure followed by quality improvement or persistent failure."""

    def __init__(
        self, fail_first_round: bool = False, persistent_failure: bool = False
    ) -> None:
        self.fail_first_round = fail_first_round
        self.persistent_failure = persistent_failure
        self.eval_call_count = 0
        self.research_call_count = 0

    async def execute(self, request: AgentRequest) -> WorkerResponseEnvelope:
        run_id = request.run_id
        subtask_id = request.subtask_id

        # 1. Planner
        if request.agent_role == AgentRole.PLANNER:
            return WorkerResponseEnvelope(
                envelope_id=f"env_{subtask_id}",
                dispatch_id=f"disp_{subtask_id}",
                run_id=run_id,
                subtask_id=subtask_id,
                status=TaskStatus.COMPLETED,
                response=AgentResponse(
                    response_id=f"resp_{subtask_id}",
                    request_id=request.request_id,
                    run_id=run_id,
                    subtask_id=subtask_id,
                    agent_role=AgentRole.PLANNER,
                    output_data={
                        "plan_id": f"plan_{run_id}",
                        "planned_subtasks": [
                            SubtaskNode(
                                subtask_id="task_res_1",
                                task_type=TaskType.WEB_SEARCH,
                                objective="Initial research query",
                                assigned_role=AgentRole.RESEARCHER,
                            ).model_dump()
                        ],
                        "edges": [],
                    },
                    execution_time_ms=10,
                    token_usage=TokenUsage(
                        prompt_tokens=10, completion_tokens=20, total_tokens=30
                    ),
                ),
                worker_id="planner_mock",
            )

        # 2. Researcher
        if request.agent_role == AgentRole.RESEARCHER:
            self.research_call_count += 1
            return WorkerResponseEnvelope(
                envelope_id=f"env_{subtask_id}",
                dispatch_id=f"disp_{subtask_id}",
                run_id=run_id,
                subtask_id=subtask_id,
                status=TaskStatus.COMPLETED,
                response=AgentResponse(
                    response_id=f"resp_{subtask_id}",
                    request_id=request.request_id,
                    run_id=run_id,
                    subtask_id=subtask_id,
                    agent_role=AgentRole.RESEARCHER,
                    output_data={"evidence_count": 3, "query": request.goal_context},
                    execution_time_ms=15,
                    token_usage=TokenUsage(
                        prompt_tokens=15, completion_tokens=25, total_tokens=40
                    ),
                ),
                worker_id="researcher_mock",
            )

        # 3. Analyst
        if request.agent_role == AgentRole.ANALYST:
            finding = KeyFinding(
                finding_id=f"kf_{subtask_id}",
                title="Synthesized Finding",
                narrative="Synthesized empirical findings from evidence pool.",
                run_id=run_id,
            )
            return WorkerResponseEnvelope(
                envelope_id=f"env_{subtask_id}",
                dispatch_id=f"disp_{subtask_id}",
                run_id=run_id,
                subtask_id=subtask_id,
                status=TaskStatus.COMPLETED,
                response=AgentResponse(
                    response_id=f"resp_{subtask_id}",
                    request_id=request.request_id,
                    run_id=run_id,
                    subtask_id=subtask_id,
                    agent_role=AgentRole.ANALYST,
                    output_data={"findings": [finding.model_dump()], "claims": []},
                    execution_time_ms=20,
                    token_usage=TokenUsage(
                        prompt_tokens=20, completion_tokens=30, total_tokens=50
                    ),
                ),
                worker_id="analyst_mock",
            )

        # 4. Verifier
        if request.agent_role == AgentRole.VERIFIER:
            citation = CitationReference(
                citation_key="[CIT-01]",
                evidence_id="ev_01",
                source_url="https://arxiv.org/abs/test-verification",
                title="Test Source",
                domain="arxiv.org",
                run_id=run_id,
            )
            return WorkerResponseEnvelope(
                envelope_id=f"env_{subtask_id}",
                dispatch_id=f"disp_{subtask_id}",
                run_id=run_id,
                subtask_id=subtask_id,
                status=TaskStatus.COMPLETED,
                response=AgentResponse(
                    response_id=f"resp_{subtask_id}",
                    request_id=request.request_id,
                    run_id=run_id,
                    subtask_id=subtask_id,
                    agent_role=AgentRole.VERIFIER,
                    output_data={
                        "citations": [citation.model_dump()],
                        "contradictions": [],
                    },
                    execution_time_ms=20,
                    token_usage=TokenUsage(
                        prompt_tokens=20, completion_tokens=20, total_tokens=40
                    ),
                ),
                worker_id="verifier_mock",
            )

        # 5. Evaluator
        if request.agent_role == AgentRole.EVALUATOR:
            self.eval_call_count += 1
            if self.fail_first_round and self.eval_call_count == 1:
                # Failing score on round 1
                eval_rep = EvaluationReport(
                    report_id=f"rep_eval_{self.eval_call_count}",
                    run_id=run_id,
                    passed=False,
                    overall_score=0.65,
                    completeness_score=0.60,
                    citation_coverage_score=0.70,
                    contradiction_rate=0.0,
                    unsupported_claim_rate=0.35,
                    source_diversity_score=0.70,
                    rubric_scores=(
                        EvaluationRubricScore(
                            rubric_name="Completeness",
                            score=0.60,
                            weight=0.50,
                            feedback="Missing depth on implementation details.",
                        ),
                    ),
                    summary_critique="Incomplete initial synthesis requiring additional research.",
                )
            elif self.persistent_failure:
                # Persistent failure
                eval_rep = EvaluationReport(
                    report_id=f"rep_eval_{self.eval_call_count}",
                    run_id=run_id,
                    passed=False,
                    overall_score=0.60,
                    completeness_score=0.60,
                    citation_coverage_score=0.60,
                    contradiction_rate=0.0,
                    unsupported_claim_rate=0.40,
                    source_diversity_score=0.60,
                    summary_critique="Persistent failure across iterations.",
                )
            else:
                # Passing score
                eval_rep = EvaluationReport(
                    report_id=f"rep_eval_{self.eval_call_count}",
                    run_id=run_id,
                    passed=True,
                    overall_score=0.92,
                    completeness_score=0.95,
                    citation_coverage_score=0.90,
                    contradiction_rate=0.0,
                    unsupported_claim_rate=0.05,
                    source_diversity_score=0.85,
                    summary_critique="Comprehensive, fully grounded synthesis.",
                )

            return WorkerResponseEnvelope(
                envelope_id=f"env_{subtask_id}",
                dispatch_id=f"disp_{subtask_id}",
                run_id=run_id,
                subtask_id=subtask_id,
                status=TaskStatus.COMPLETED,
                response=AgentResponse(
                    response_id=f"resp_{subtask_id}",
                    request_id=request.request_id,
                    run_id=run_id,
                    subtask_id=subtask_id,
                    agent_role=AgentRole.EVALUATOR,
                    output_data=eval_rep.model_dump(),
                    execution_time_ms=25,
                    token_usage=TokenUsage(
                        prompt_tokens=25, completion_tokens=35, total_tokens=60
                    ),
                ),
                worker_id="evaluator_mock",
            )

        # 6. Reporter
        if request.agent_role == AgentRole.REPORTER:
            dossier = ResearchDossier(
                dossier_id=f"dossier_{run_id}",
                run_id=run_id,
                goal_query="Test goal query",
                methodology_summary="Decomposition and refinement methodology.",
                executive_summary="Final synthesized executive summary.",
                key_findings=(
                    KeyFinding(
                        finding_id="kf_final",
                        title="Final Insight",
                        narrative="Refined narrative with full factual backing.",
                        run_id=run_id,
                    ),
                ),
                citations=(
                    CitationReference(
                        citation_key="[CIT-01]",
                        evidence_id="ev_01",
                        source_url="https://arxiv.org/abs/test-verification",
                        title="Test Source",
                        domain="arxiv.org",
                        run_id=run_id,
                    ),
                ),
                confidence_rating=0.92,
                verification_status=VerificationStatus.VERIFIED,
                markdown_report="# Final Research Dossier\nRefined and verified content.",
            )
            return WorkerResponseEnvelope(
                envelope_id=f"env_{subtask_id}",
                dispatch_id=f"disp_{subtask_id}",
                run_id=run_id,
                subtask_id=subtask_id,
                status=TaskStatus.COMPLETED,
                response=AgentResponse(
                    response_id=f"resp_{subtask_id}",
                    request_id=request.request_id,
                    run_id=run_id,
                    subtask_id=subtask_id,
                    agent_role=AgentRole.REPORTER,
                    output_data=dossier.model_dump(),
                    execution_time_ms=30,
                    token_usage=TokenUsage(
                        prompt_tokens=30, completion_tokens=50, total_tokens=80
                    ),
                ),
                worker_id="reporter_mock",
            )

        return WorkerResponseEnvelope(
            envelope_id=f"env_{subtask_id}",
            dispatch_id=f"disp_{subtask_id}",
            run_id=run_id,
            subtask_id=subtask_id,
            status=TaskStatus.FAILED,
            worker_id="unknown_mock",
        )


class TestSelfCorrectionAndRefinementE2E:
    """End-to-end integration tests for autonomous refinement cycles."""

    @pytest.mark.asyncio
    async def test_initial_pass_skips_refinement(self) -> None:
        """Verify that an initially passing evaluation proceeds straight to reporting with 0 refinement iterations."""
        settings = AppSettings(
            APP_ENV="test",
            API_AUTH_ENABLED=False,
            ARTIFACT_STORAGE_PROVIDER="in_memory",
            MAX_REFINEMENT_LOOPS=2,
            REFINEMENT_ENABLED=True,
        )

        mock_router = MockDynamicRefinementRouter(fail_first_round=False)
        run_repo = InMemoryRunRepository()
        artifact_storage = create_artifact_storage(settings=settings)

        run_id = "run_pass_01"
        context = _make_context(run_id=run_id, goal_query="Quantum Error Mitigation")
        runs = {run_id: context}

        worker = ResearchJobWorker(
            router=mock_router,
            run_context_resolver=lambda r_id: runs.get(r_id),
            run_repo=run_repo,
            artifact_storage=artifact_storage,
        )

        envelope = JobEnvelope(
            job_id="job_01",
            run_id=run_id,
            goal_query="Quantum Error Mitigation",
        )

        result_envelope = await worker.handle_job(envelope)
        assert result_envelope.status == JobStatus.COMPLETED
        assert context.status == RunStage.COMPLETED
        assert context.dossier is not None
        assert mock_router.eval_call_count == 1  # Only 1 initial evaluation executed
        assert mock_router.research_call_count == 1

    @pytest.mark.asyncio
    async def test_failing_then_improving_run_triggers_refinement(self) -> None:
        """Verify that an initial evaluation failure triggers targeted refinement and achieves pass on round 2."""
        settings = AppSettings(
            APP_ENV="test",
            API_AUTH_ENABLED=False,
            ARTIFACT_STORAGE_PROVIDER="in_memory",
            MAX_REFINEMENT_LOOPS=2,
            REFINEMENT_ENABLED=True,
        )

        mock_router = MockDynamicRefinementRouter(fail_first_round=True)
        run_repo = InMemoryRunRepository()
        artifact_storage = create_artifact_storage(settings=settings)

        run_id = "run_refine_02"
        context = _make_context(
            run_id=run_id, goal_query="Biomedical mRNA LNP Delivery"
        )
        runs = {run_id: context}

        worker = ResearchJobWorker(
            router=mock_router,
            run_context_resolver=lambda r_id: runs.get(r_id),
            run_repo=run_repo,
            artifact_storage=artifact_storage,
        )

        envelope = JobEnvelope(
            job_id="job_02",
            run_id=run_id,
            goal_query="Biomedical mRNA LNP Delivery",
        )

        result_envelope = await worker.handle_job(envelope)
        assert result_envelope.error is None
        assert result_envelope.status == JobStatus.COMPLETED
        assert context.status == RunStage.COMPLETED
        assert context.dossier is not None
        assert mock_router.eval_call_count == 2  # Round 1 (failed) + Round 2 (passed)
        assert (
            mock_router.research_call_count >= 2
        )  # Initial research + refinement research

    @pytest.mark.asyncio
    async def test_persistent_failure_terminates_at_max_loops(self) -> None:
        """Verify that persistent failure strictly stops after reaching MAX_REFINEMENT_LOOPS."""
        settings = AppSettings(
            APP_ENV="test",
            API_AUTH_ENABLED=False,
            ARTIFACT_STORAGE_PROVIDER="in_memory",
            MAX_REFINEMENT_LOOPS=2,
            REFINEMENT_ENABLED=True,
        )

        mock_router = MockDynamicRefinementRouter(persistent_failure=True)
        run_repo = InMemoryRunRepository()
        artifact_storage = create_artifact_storage(settings=settings)

        run_id = "run_exhaust_03"
        context = _make_context(run_id=run_id, goal_query="Wholesale CBDC Settlement")
        runs = {run_id: context}

        worker = ResearchJobWorker(
            router=mock_router,
            run_context_resolver=lambda r_id: runs.get(r_id),
            run_repo=run_repo,
            artifact_storage=artifact_storage,
        )

        envelope = JobEnvelope(
            job_id="job_03",
            run_id=run_id,
            goal_query="Wholesale CBDC Settlement",
        )

        result_envelope = await worker.handle_job(envelope)
        assert result_envelope.status == JobStatus.COMPLETED
        # Initial evaluation + exactly 2 refinement evaluations = 3 total evaluation calls
        assert mock_router.eval_call_count == 3

    @pytest.mark.asyncio
    async def test_cancellation_during_refinement(self) -> None:
        """Verify that cancelling during a refinement loop halts execution cleanly."""
        mock_router = MockDynamicRefinementRouter(fail_first_round=True)
        run_repo = InMemoryRunRepository()

        run_id = "run_cancel_04"
        cancellation_token = CancellationToken()
        context = _make_context(
            run_id=run_id,
            goal_query="Technical RAG Analysis",
            cancellation_token=cancellation_token,
        )
        runs = {run_id: context}

        worker = ResearchJobWorker(
            router=mock_router,
            run_context_resolver=lambda r_id: runs.get(r_id),
            run_repo=run_repo,
        )

        # Cancel immediately before execution starts
        cancellation_token.cancel()

        envelope = JobEnvelope(
            job_id="job_04",
            run_id=run_id,
            goal_query="Technical RAG Analysis",
        )

        result_envelope = await worker.handle_job(envelope)
        assert result_envelope.status == JobStatus.CANCELLED
        assert context.status == RunStage.CANCELLED
