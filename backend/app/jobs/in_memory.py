"""In-memory pub/sub implementation for local execution and deterministic testing."""

import asyncio
from datetime import UTC, datetime
from typing import Any

from app.jobs.protocols import (
    JobConsumerProtocol,
    JobEnvelope,
    JobHandlerProtocol,
    JobPublisherProtocol,
    JobStatus,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class InMemoryJobQueue:
    """Thread/async-safe in-memory queue container holding pending, active, and dead-lettered jobs."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[JobEnvelope] = asyncio.Queue()
        self._jobs: dict[str, JobEnvelope] = {}
        self._dead_letter_queue: list[JobEnvelope] = []
        self._lock = asyncio.Lock()

    async def put(self, envelope: JobEnvelope) -> None:
        """Enqueue a new or retried job envelope."""
        async with self._lock:
            self._jobs[envelope.job_id] = envelope
        await self._queue.put(envelope)

    async def get(self) -> JobEnvelope:
        """Retrieve the next queued job envelope (FIFO)."""
        return await self._queue.get()

    def qsize(self) -> int:
        """Return current number of items waiting in queue."""
        return self._queue.qsize()

    def size(self) -> int:
        """Alias for qsize to return number of queued items."""
        return self._queue.qsize()

    def task_done(self) -> None:
        """Signal completion of the retrieved queue item."""
        self._queue.task_done()

    async def update_job(self, envelope: JobEnvelope) -> None:
        """Update the tracked state of a job envelope."""
        async with self._lock:
            self._jobs[envelope.job_id] = envelope

    async def add_to_dead_letter(self, envelope: JobEnvelope) -> None:
        """Record an unrecoverable or retry-exhausted job envelope to the dead letter queue."""
        dead_envelope = envelope.with_status(
            JobStatus.DEAD_LETTERED, completed_at=_utc_now()
        )
        async with self._lock:
            self._jobs[envelope.job_id] = dead_envelope
            self._dead_letter_queue.append(dead_envelope)

    async def get_job(self, job_id: str) -> JobEnvelope | None:
        """Retrieve the latest snapshot of a job envelope by job_id."""
        async with self._lock:
            return self._jobs.get(job_id)

    async def get_dead_letter_jobs(self) -> list[JobEnvelope]:
        """Return a snapshot of all dead-lettered jobs."""
        async with self._lock:
            return list(self._dead_letter_queue)

    @property
    def pending_count(self) -> int:
        """Return the number of currently pending queue items."""
        return self._queue.qsize()


class InMemoryJobPublisher(JobPublisherProtocol):
    """Publishes research job requests to an InMemoryJobQueue."""

    def __init__(self, queue: InMemoryJobQueue) -> None:
        self._queue = queue

    async def publish(self, envelope: JobEnvelope) -> str:
        """Enqueue a research job envelope."""
        queued_envelope = (
            envelope
            if envelope.status == JobStatus.QUEUED
            else envelope.with_status(JobStatus.QUEUED)
        )
        await self._queue.put(queued_envelope)
        return queued_envelope.job_id


class InMemoryJobConsumer(JobConsumerProtocol):
    """Consumes and coordinates research jobs from an InMemoryJobQueue via a JobHandler."""

    def __init__(
        self,
        queue: InMemoryJobQueue,
        handler: JobHandlerProtocol,
        worker_concurrency: int = 2,
    ) -> None:
        self._queue = queue
        self._handler = handler
        self._worker_concurrency = max(1, worker_concurrency)
        self._running = False
        self._tasks: list[asyncio.Task[Any]] = []
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Start the background consumer worker tasks."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._tasks = [
            asyncio.create_task(self._worker_loop(i))
            for i in range(self._worker_concurrency)
        ]

    async def stop(self) -> None:
        """Gracefully stop background consumer tasks."""
        if not self._running:
            return
        self._running = False
        self._stop_event.set()

        for task in self._tasks:
            task.cancel()

        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    def is_running(self) -> bool:
        """Return whether the consumer worker pool is active."""
        return self._running

    async def _worker_loop(self, _worker_idx: int) -> None:
        """Worker loop continuously popping jobs, invoking the handler, and handling retries."""
        while self._running:
            try:
                # Wait for next job or cancellation
                try:
                    envelope = await asyncio.wait_for(self._queue.get(), timeout=0.25)
                except TimeoutError:
                    continue

                # Process the job through the handler
                await self._process_envelope(envelope)
                self._queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception:
                # Keep worker loop alive despite unexpected supervisor errors
                await asyncio.sleep(0.1)

    async def _process_envelope(self, envelope: JobEnvelope) -> None:
        """Execute handler on envelope with retry and dead-letter routing."""
        running_envelope = envelope.with_status(
            JobStatus.RUNNING, started_at=_utc_now()
        )
        await self._queue.update_job(running_envelope)

        try:
            result_envelope = await self._handler.handle_job(running_envelope)
        except Exception as e:
            # Handler raised unexpected exception
            result_envelope = running_envelope.with_status(
                JobStatus.FAILED,
                error=str(e),
                is_retryable=True,
                completed_at=_utc_now(),
            )

        if result_envelope.status in (JobStatus.COMPLETED, JobStatus.CANCELLED):
            # Final state reached
            final_envelope = result_envelope.with_status(
                result_envelope.status, completed_at=_utc_now()
            )
            await self._queue.update_job(final_envelope)

        elif result_envelope.status == JobStatus.FAILED:
            # Check retry eligibility
            if (
                result_envelope.is_retryable
                and result_envelope.attempt < result_envelope.max_attempts
            ):
                # Schedule retry
                next_attempt = result_envelope.attempt + 1
                retry_envelope = result_envelope.with_status(
                    JobStatus.QUEUED,
                    attempt=next_attempt,
                    started_at=None,
                    completed_at=None,
                )
                await self._queue.put(retry_envelope)
            else:
                # Exhausted retries or non-retryable error -> move to dead letter queue
                await self._queue.add_to_dead_letter(result_envelope)


__all__ = [
    "InMemoryJobConsumer",
    "InMemoryJobPublisher",
    "InMemoryJobQueue",
]
