"""Unit tests for InMemoryJobQueue, InMemoryJobPublisher, and InMemoryJobConsumer."""

import asyncio

import pytest

from app.jobs.in_memory import (
    InMemoryJobConsumer,
    InMemoryJobPublisher,
    InMemoryJobQueue,
)
from app.jobs.protocols import (
    JobEnvelope,
    JobStatus,
)


@pytest.mark.asyncio
async def test_in_memory_queue_fifo_ordering() -> None:
    """Test 1: Verify FIFO ordering of queue get operations."""
    queue = InMemoryJobQueue()
    env1 = JobEnvelope(job_id="job_1", run_id="run_1", goal_query="First inquiry")
    env2 = JobEnvelope(job_id="job_2", run_id="run_2", goal_query="Second inquiry")

    await queue.put(env1)
    await queue.put(env2)

    assert queue.pending_count == 2
    popped1 = await queue.get()
    assert popped1.job_id == "job_1"
    popped2 = await queue.get()
    assert popped2.job_id == "job_2"


@pytest.mark.asyncio
async def test_in_memory_publisher_publish() -> None:
    """Test 2: Verify publisher enqueues job envelope."""
    queue = InMemoryJobQueue()
    publisher = InMemoryJobPublisher(queue)

    env = JobEnvelope(job_id="job_pub_1", run_id="run_pub_1", goal_query="Publish test")
    published_id = await publisher.publish(env)

    assert published_id == "job_pub_1"
    assert queue.pending_count == 1
    stored = await queue.get_job("job_pub_1")
    assert stored is not None
    assert stored.status == JobStatus.QUEUED


@pytest.mark.asyncio
async def test_in_memory_consumer_successful_processing() -> None:
    """Test 3: Verify consumer handles successful execution cleanly."""
    queue = InMemoryJobQueue()
    publisher = InMemoryJobPublisher(queue)

    processed_jobs: list[str] = []

    class SuccessHandler:
        async def handle_job(self, envelope: JobEnvelope) -> JobEnvelope:
            processed_jobs.append(envelope.job_id)
            return envelope.with_status(JobStatus.COMPLETED)

    consumer = InMemoryJobConsumer(queue, SuccessHandler(), worker_concurrency=1)
    await consumer.start()
    assert consumer.is_running() is True

    try:
        env = JobEnvelope(
            job_id="job_success_1", run_id="run_1", goal_query="Success query"
        )
        await publisher.publish(env)

        for _ in range(20):
            job_snapshot = await queue.get_job("job_success_1")
            if job_snapshot and job_snapshot.status == JobStatus.COMPLETED:
                break
            await asyncio.sleep(0.05)

        job_final = await queue.get_job("job_success_1")
        assert job_final is not None
        assert job_final.status == JobStatus.COMPLETED
        assert "job_success_1" in processed_jobs
    finally:
        await consumer.stop()
        assert consumer.is_running() is False


@pytest.mark.asyncio
async def test_in_memory_consumer_retry_and_dead_letter_on_exhaustion() -> None:
    """Test 4: Verify transient failures retry up to max_attempts and then dead-letter."""
    queue = InMemoryJobQueue()
    publisher = InMemoryJobPublisher(queue)

    attempts_seen: list[int] = []

    class FailingHandler:
        async def handle_job(self, envelope: JobEnvelope) -> JobEnvelope:
            attempts_seen.append(envelope.attempt)
            return envelope.with_status(
                JobStatus.FAILED, error="Transient timeout", is_retryable=True
            )

    consumer = InMemoryJobConsumer(queue, FailingHandler(), worker_concurrency=1)
    await consumer.start()

    try:
        env = JobEnvelope(
            job_id="job_retry_1",
            run_id="run_retry_1",
            goal_query="Retry query",
            max_attempts=3,
        )
        await publisher.publish(env)

        for _ in range(30):
            dead_letters = await queue.get_dead_letter_jobs()
            if dead_letters:
                break
            await asyncio.sleep(0.05)

        dead_letters = await queue.get_dead_letter_jobs()
        assert len(dead_letters) == 1
        assert dead_letters[0].job_id == "job_retry_1"
        assert dead_letters[0].status == JobStatus.DEAD_LETTERED
        assert dead_letters[0].error == "Transient timeout"
        assert attempts_seen == [1, 2, 3]
    finally:
        await consumer.stop()


@pytest.mark.asyncio
async def test_in_memory_consumer_non_retryable_dead_letter_immediately() -> None:
    """Test 5: Verify non-retryable failure transitions to dead-letter without retries."""
    queue = InMemoryJobQueue()
    publisher = InMemoryJobPublisher(queue)

    attempts_seen: list[int] = []

    class NonRetryableHandler:
        async def handle_job(self, envelope: JobEnvelope) -> JobEnvelope:
            attempts_seen.append(envelope.attempt)
            return envelope.with_status(
                JobStatus.FAILED, error="Security violation", is_retryable=False
            )

    consumer = InMemoryJobConsumer(queue, NonRetryableHandler(), worker_concurrency=1)
    await consumer.start()

    try:
        env = JobEnvelope(
            job_id="job_non_ret_1",
            run_id="run_non_ret_1",
            goal_query="Non-retryable query",
            max_attempts=5,
        )
        await publisher.publish(env)

        for _ in range(20):
            dead_letters = await queue.get_dead_letter_jobs()
            if dead_letters:
                break
            await asyncio.sleep(0.05)

        dead_letters = await queue.get_dead_letter_jobs()
        assert len(dead_letters) == 1
        assert dead_letters[0].job_id == "job_non_ret_1"
        assert dead_letters[0].status == JobStatus.DEAD_LETTERED
        assert attempts_seen == [1]  # Only 1 attempt made
    finally:
        await consumer.stop()
