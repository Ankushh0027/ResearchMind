"""Research service orchestrating asynchronous background runs, durable persistence, and event streams."""

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
from app.orchestration.events import ExecutionEvent
from app.orchestration.protocols import (
    CheckpointRepositoryProtocol,
    WorkerProtocol,
)
from app.orchestration.router import create_default_worker_router
from app.orchestration.runtime import InMemoryEventSink
from app.persistence.factory import (
    create_checkpoint_repository,
    create_run_repository,
)
from app.persistence.protocols import (
    RunContext,
    RunRecord,
    RunRepositoryProtocol,
)
from app.state.models import ResearchGoal


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ResearchService:
    """Service layer managing research run lifecycles, durable persistence, and SSE telemetry."""

    def __init__(
        self,
        router: WorkerProtocol | None = None,
        publisher: JobPublisherProtocol | None = None,
        consumer: JobConsumerProtocol | None = None,
        worker: ResearchJobWorker | None = None,
        run_repo: RunRepositoryProtocol | None = None,
        checkpoint_repo: CheckpointRepositoryProtocol | None = None,
        max_concurrency: int = 4,
    ) -> None:
        self._router = router or create_default_worker_router()
        self._max_concurrency = max_concurrency
        self._run_repo = run_repo or create_run_repository()
        self._checkpoint_repo = checkpoint_repo or create_checkpoint_repository()
        self._runs: dict[str, RunContext] = {}
        self._lock = asyncio.Lock()

        if publisher is None or consumer is None:
            queue = InMemoryJobQueue()
            self._worker = worker or ResearchJobWorker(
                router=self._router,
                run_context_resolver=self._get_run_context,
                run_repo=self._run_repo,
                checkpoint_repo=self._checkpoint_repo,
                max_concurrency=self._max_concurrency,
            )
            self._worker.set_run_context_resolver(self._get_run_context)
            self._worker.set_run_repository(self._run_repo)
            self._worker.set_checkpoint_repository(self._checkpoint_repo)
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
                run_repo=self._run_repo,
                checkpoint_repo=self._checkpoint_repo,
                max_concurrency=self._max_concurrency,
            )
            self._worker.set_run_context_resolver(self._get_run_context)
            self._worker.set_run_repository(self._run_repo)
            self._worker.set_checkpoint_repository(self._checkpoint_repo)

    @property
    def run_repository(self) -> RunRepositoryProtocol:
        """Return the underlying RunRepository."""
        return self._run_repo

    @property
    def checkpoint_repository(self) -> CheckpointRepositoryProtocol:
        """Return the underlying CheckpointRepository."""
        return self._checkpoint_repo

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
        """Initialize research run, persist initial record, publish JobEnvelope, and return summary."""
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
        token = CancellationToken()

        context = RunContext(
            run_id=run_id,
            goal=goal,
            cancellation_token=token,
            event_sink=event_sink,
            checkpoint_repo=self._checkpoint_repo,
        )

        # 1. Persist initial RunRecord into durable repository
        initial_record = RunRecord(
            run_id=run_id,
            goal=goal,
            status=RunStage.QUEUED,
            version=1,
            created_at=_utc_now(),
            updated_at=_utc_now(),
        )
        await self._run_repo.create_run(initial_record)

        # 2. Track in-memory execution context
        async with self._lock:
            self._runs[run_id] = context

        # 3. Publish JobEnvelope
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
        if context is not None:
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

        # Look up from durable repository if not active in process RAM
        record = await self._run_repo.get_run(run_id)
        if record is None:
            return None

        return RunDetailResponse(
            run_id=record.run_id,
            plan_id=record.plan_id,
            goal_query=record.goal.query,
            status=record.status,
            completed_task_ids=tuple(record.completed_task_ids),
            failed_task_ids=tuple(record.failed_task_ids),
            cancelled_task_ids=tuple(record.cancelled_task_ids),
            total_token_usage=record.total_token_usage,
            duration_seconds=record.duration_seconds,
            dossier=record.dossier,
            error=record.error,
            created_at=record.created_at,
        )

    async def cancel_run(self, run_id: str) -> CancelRunResponse:
        """Signal cooperative cancellation for an in-flight research run."""
        context = self._runs.get(run_id)
        record = await self._run_repo.get_run(run_id)

        if context is None and record is None:
            raise KeyError(f"Research run '{run_id}' not found")

        if context is not None:
            context.cancellation_token.cancel(reason="Cancelled by client request")
            context.status = RunStage.CANCELLED
            context.duration_seconds = time.monotonic() - context.start_time

        if record is not None:
            updated_record = record.with_updates(
                status=RunStage.CANCELLED,
                is_cancelled=True,
                cancellation_reason="Cancelled by client request",
            )
            await self._run_repo.update_run(updated_record)

        return CancelRunResponse(
            run_id=run_id,
            status=RunStage.CANCELLED,
            message="Cancellation requested successfully",
        )

    async def stream_events(self, run_id: str) -> AsyncIterator[dict[str, Any]]:
        """Yield Server-Sent Events (SSE) detailing real-time run progress and task transitions."""
        context = self._runs.get(run_id)
        if not context:
            record = await self._run_repo.get_run(run_id)
            if not record:
                raise KeyError(f"Research run '{run_id}' not found")
            # If historical run without active sink, exit immediately
            return

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
