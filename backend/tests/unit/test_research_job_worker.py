"""Unit tests for ResearchJobWorker gateway."""

import pytest

from app.api.service import RunContext
from app.common.enums import RunStage
from app.jobs.protocols import JobEnvelope, JobStatus
from app.jobs.worker import ResearchJobWorker
from app.orchestration.cancellation import CancellationToken
from app.orchestration.contracts import AgentError, AgentRequest, WorkerResponseEnvelope
from app.orchestration.router import create_default_worker_router
from app.orchestration.runtime import InMemoryCheckpointRepository, InMemoryEventSink
from app.state.models import ResearchGoal


@pytest.fixture
def run_context() -> RunContext:
    goal = ResearchGoal(
        goal_id="goal_worker_1",
        query="Investigate topological phases of matter.",
        max_subtasks=4,
    )
    return RunContext(
        run_id="run_worker_1",
        goal=goal,
        cancellation_token=CancellationToken(),
        event_sink=InMemoryEventSink(),
        checkpoint_repo=InMemoryCheckpointRepository(),
    )


@pytest.mark.asyncio
async def test_research_job_worker_success(run_context: RunContext) -> None:
    """Test 1: Verify worker executes pipeline and attaches ResearchDossier to context."""
    runs = {run_context.run_id: run_context}
    worker = ResearchJobWorker(
        router=create_default_worker_router(),
        run_context_resolver=lambda r_id: runs.get(r_id),
        max_concurrency=4,
    )

    envelope = JobEnvelope(
        job_id="job_w_1",
        run_id=run_context.run_id,
        goal_query=run_context.goal.query,
    )

    result_env = await worker.handle_job(envelope)
    assert result_env.status == JobStatus.COMPLETED
    assert run_context.status == RunStage.COMPLETED
    assert run_context.dossier is not None
    assert len(run_context.dossier.key_findings) >= 1
    assert "## Executive Summary" in run_context.dossier.markdown_report


@pytest.mark.asyncio
async def test_research_job_worker_cancellation(run_context: RunContext) -> None:
    """Test 2: Verify worker halts immediately when cancellation is requested."""
    run_context.cancellation_token.cancel("User cancelled")
    runs = {run_context.run_id: run_context}
    worker = ResearchJobWorker(
        router=create_default_worker_router(),
        run_context_resolver=lambda r_id: runs.get(r_id),
    )

    envelope = JobEnvelope(
        job_id="job_w_cancel",
        run_id=run_context.run_id,
        goal_query=run_context.goal.query,
    )

    result_env = await worker.handle_job(envelope)
    assert result_env.status == JobStatus.CANCELLED
    assert run_context.status == RunStage.CANCELLED


@pytest.mark.asyncio
async def test_research_job_worker_invalid_payload() -> None:
    """Test 3: Verify worker rejects invalid payload as non-retryable failure."""
    worker = ResearchJobWorker(
        router=create_default_worker_router(),
        run_context_resolver=lambda _r: None,
    )

    # Empty run_id
    env = JobEnvelope.model_construct(
        job_id="job_w_bad",
        run_id="",
        goal_query="Valid goal",
        domain_tags=(),
        constraints={},
        max_subtasks=5,
        attempt=1,
        max_attempts=3,
        status=JobStatus.QUEUED,
        created_at=None,
        started_at=None,
        completed_at=None,
        error=None,
        is_retryable=True,
        metadata={},
    )

    result = await worker.handle_job(env)
    assert result.status == JobStatus.FAILED
    assert result.is_retryable is False
    assert "invalid run_id" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_research_job_worker_missing_run_context() -> None:
    """Test 4: Verify worker returns non-retryable failure when RunContext is absent."""
    worker = ResearchJobWorker(
        router=create_default_worker_router(),
        run_context_resolver=lambda _r: None,
    )

    env = JobEnvelope(
        job_id="job_w_missing",
        run_id="run_nonexistent",
        goal_query="Valid research goal inquiry",
    )

    result = await worker.handle_job(env)
    assert result.status == JobStatus.FAILED
    assert result.is_retryable is False
    assert "not found" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_research_job_worker_planner_failure_error_preservation(
    run_context: RunContext,
) -> None:
    """Test 5: Verify worker preserves planner failure details and retryable flags."""
    from app.common.enums import TaskStatus

    class FailingPlannerRouter:
        async def execute(self, request: AgentRequest) -> WorkerResponseEnvelope:
            return WorkerResponseEnvelope(
                envelope_id=f"env_{request.request_id}",
                dispatch_id=request.request_id,
                run_id=request.run_id,
                subtask_id=request.subtask_id,
                status=TaskStatus.FAILED,
                error=AgentError(
                    error_code="TRANSIENT_LLM_TIMEOUT",
                    error_type="TimeoutError",
                    message="Gemini API upstream rate limit",
                    is_retryable=True,
                ),
            )

    runs = {run_context.run_id: run_context}
    worker = ResearchJobWorker(
        router=FailingPlannerRouter(),
        run_context_resolver=lambda r_id: runs.get(r_id),
    )

    envelope = JobEnvelope(
        job_id="job_w_fail",
        run_id=run_context.run_id,
        goal_query=run_context.goal.query,
    )

    result_env = await worker.handle_job(envelope)
    assert result_env.status == JobStatus.FAILED
    assert result_env.is_retryable is True
    assert "upstream rate limit" in (result_env.error or "")
    assert run_context.status == RunStage.FAILED


@pytest.mark.asyncio
async def test_research_job_worker_run_isolation() -> None:
    """Test 6: Verify worker executes distinct runs without cross-talk or shared state."""
    goal1 = ResearchGoal(goal_id="g1", query="Query 1 topic", max_subtasks=3)
    goal2 = ResearchGoal(goal_id="g2", query="Query 2 topic", max_subtasks=3)

    ctx1 = RunContext(
        run_id="run_iso_1",
        goal=goal1,
        cancellation_token=CancellationToken(),
        event_sink=InMemoryEventSink(),
        checkpoint_repo=InMemoryCheckpointRepository(),
    )
    ctx2 = RunContext(
        run_id="run_iso_2",
        goal=goal2,
        cancellation_token=CancellationToken(),
        event_sink=InMemoryEventSink(),
        checkpoint_repo=InMemoryCheckpointRepository(),
    )

    runs = {ctx1.run_id: ctx1, ctx2.run_id: ctx2}
    worker = ResearchJobWorker(
        router=create_default_worker_router(),
        run_context_resolver=lambda r_id: runs.get(r_id),
    )

    env1 = JobEnvelope(job_id="j1", run_id=ctx1.run_id, goal_query=ctx1.goal.query)
    env2 = JobEnvelope(job_id="j2", run_id=ctx2.run_id, goal_query=ctx2.goal.query)

    res1 = await worker.handle_job(env1)
    res2 = await worker.handle_job(env2)

    assert res1.status == JobStatus.COMPLETED
    assert res2.status == JobStatus.COMPLETED
    assert ctx1.dossier is not None
    assert ctx2.dossier is not None
    assert ctx1.dossier.dossier_id != ctx2.dossier.dossier_id
