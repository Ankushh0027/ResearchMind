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
from app.common.enums import RunStage
from app.intelligence.models import ResearchDossier
from app.jobs.in_memory import (
    InMemoryJobConsumer,
    InMemoryJobPublisher,
    InMemoryJobQueue,
)
from app.jobs.protocols import (
    JobConsumerProtocol,
    JobEnvelope,
    JobPublisherProtocol,
)
from app.jobs.worker import ResearchJobWorker
from app.orchestration.cancellation import CancellationToken
from app.orchestration.contracts import TokenUsage
from app.orchestration.events import ExecutionEvent
from app.orchestration.protocols import (
    CheckpointRepositoryProtocol,
    WorkerProtocol,
)
from app.orchestration.router import create_default_worker_router
from app.orchestration.runtime import (
    InMemoryCheckpointRepository,
    InMemoryEventSink,
)
from app.state.models import ResearchGoal


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


class ResearchService:
    """Service layer managing research run lifecycles, background coordination, and SSE telemetry."""

    def __init__(
        self,
        router: WorkerProtocol | None = None,
        publisher: JobPublisherProtocol | None = None,
        consumer: JobConsumerProtocol | None = None,
        worker: ResearchJobWorker | None = None,
        max_concurrency: int = 4,
    ) -> None:
        self._router = router or create_default_worker_router()
        self._max_concurrency = max_concurrency
        self._runs: dict[str, RunContext] = {}
        self._lock = asyncio.Lock()

        if publisher is None or consumer is None:
            queue = InMemoryJobQueue()
            self._worker = worker or ResearchJobWorker(
                router=self._router,
                run_context_resolver=self._get_run_context,
                max_concurrency=self._max_concurrency,
            )
            self._worker.set_run_context_resolver(self._get_run_context)
            self._publisher = publisher or InMemoryJobPublisher(queue)
            self._consumer = consumer or InMemoryJobConsumer(
                queue=queue, handler=self._worker, worker_concurrency=2
            )
        else:
            self._publisher = publisher
            self._consumer = consumer
            self._worker = worker or ResearchJobWorker(
                router=self._router,
                run_context_resolver=self._get_run_context,
                max_concurrency=self._max_concurrency,
            )
            self._worker.set_run_context_resolver(self._get_run_context)

    def _get_run_context(self, run_id: str) -> RunContext | None:
        """Resolve the RunContext container for a given run ID."""
        return self._runs.get(run_id)

    async def start(self) -> None:
        """Start the asynchronous background job consumer loop."""
        await self._consumer.start()

    async def stop(self) -> None:
        """Gracefully stop the background job consumer loop."""
        await self._consumer.stop()

    async def create_and_start_run(
        self, request: CreateRunRequest
    ) -> RunSummaryResponse:
        """Initialize research run, publish JobEnvelope, and return initial summary."""
        # Auto-start consumer if not active
        if not self._consumer.is_running():
            await self._consumer.start()

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

        job_envelope = JobEnvelope(
            job_id=f"job_{uuid.uuid4().hex[:12]}",
            run_id=run_id,
            goal_query=goal.query,
            domain_tags=goal.domain_tags,
            constraints=goal.constraints,
            max_subtasks=goal.max_subtasks,
        )

        await self._publisher.publish(job_envelope)

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

        # Compute live duration if still active
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


__all__ = ["ResearchService", "RunContext"]
