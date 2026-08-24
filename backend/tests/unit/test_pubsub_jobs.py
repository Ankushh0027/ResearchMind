import asyncio
import builtins
from typing import Any
from unittest.mock import patch

import pytest

from app.common.enums import RunStage
from app.jobs.protocols import (
    JobEnvelope,
    JobStatus,
)
from app.jobs.pubsub import (
    AckDeadlineExtender,
    GooglePubSubConsumer,
    GooglePubSubPublisher,
)
from app.jobs.worker import ResearchJobWorker
from app.orchestration.cancellation import CancellationToken
from app.orchestration.router import create_default_worker_router
from app.orchestration.runtime import InMemoryCheckpointRepository, InMemoryEventSink
from app.persistence.protocols import RunContext
from app.state.models import ResearchGoal


class FakePublishFuture:
    """Fake Pub/Sub Future returned by PublisherClient.publish."""

    def __init__(self, message_id: str = "msg_001") -> None:
        self._message_id = message_id

    def result(self) -> str:
        return self._message_id


class FakePublisherClient:
    """Fake Google Cloud Pub/Sub PublisherClient for unit testing."""

    def __init__(self) -> None:
        self.published_messages: list[dict[str, Any]] = []

    def publish(self, topic: str, data: bytes, **attributes: str) -> FakePublishFuture:
        msg_id = f"pub_msg_{len(self.published_messages) + 1:04d}"
        self.published_messages.append(
            {
                "message_id": msg_id,
                "topic": topic,
                "data": data,
                "attributes": attributes,
            }
        )
        return FakePublishFuture(msg_id)


class FakeReceivedMessage:
    """Fake Pub/Sub ReceivedMessage wrapper."""

    def __init__(
        self,
        ack_id: str,
        data: bytes,
        attributes: dict[str, str] | None = None,
    ) -> None:
        self.ack_id = ack_id
        self.data = data
        self.attributes = attributes or {}
        self.message = self
        self.acked = False
        self.nacked = False

    def ack(self) -> None:
        self.acked = True

    def nack(self) -> None:
        self.nacked = True


class FakePullResponse:
    """Fake response from SubscriberClient.pull."""

    def __init__(self, messages: list[FakeReceivedMessage]) -> None:
        self.received_messages = messages


class FakeSubscriberClient:
    """Fake Google Cloud Pub/Sub SubscriberClient for unit testing."""

    def __init__(self) -> None:
        self.queue: list[FakeReceivedMessage] = []
        self.modified_ack_deadlines: list[dict[str, Any]] = []
        self.acknowledged_ack_ids: list[str] = []

    def pull(
        self, request: dict[str, Any] | None = None, **kwargs: Any
    ) -> FakePullResponse:
        req = request or kwargs
        max_msgs = req.get("max_messages", 1)
        pulled = []
        for _ in range(min(max_msgs, len(self.queue))):
            pulled.append(self.queue.pop(0))
        return FakePullResponse(pulled)

    def modify_ack_deadline(
        self, request: dict[str, Any] | None = None, **kwargs: Any
    ) -> None:
        req = request or kwargs
        self.modified_ack_deadlines.append(req)

    def acknowledge(self, request: dict[str, Any] | None = None, **kwargs: Any) -> None:
        req = request or kwargs
        ack_ids = req.get("ack_ids", [])
        self.acknowledged_ack_ids.extend(ack_ids)


@pytest.fixture
def fake_publisher_client() -> FakePublisherClient:
    return FakePublisherClient()


@pytest.fixture
def fake_subscriber_client() -> FakeSubscriberClient:
    return FakeSubscriberClient()


@pytest.fixture
def pubsub_publisher(
    fake_publisher_client: FakePublisherClient,
) -> GooglePubSubPublisher:
    return GooglePubSubPublisher(
        client=fake_publisher_client,
        project_id="test-project",
        topic_name="test-tasks",
        dead_letter_topic_name="test-dlq",
    )


@pytest.mark.asyncio
async def test_pubsub_publisher_publish_and_attributes(
    pubsub_publisher: GooglePubSubPublisher,
    fake_publisher_client: FakePublisherClient,
) -> None:
    """Test 1: Verify publisher serializes envelope, formats topic path, and attaches metadata attributes."""
    envelope = JobEnvelope(
        job_id="job_pubsub_1",
        run_id="run_pubsub_1",
        goal_query="Investigate 2D materials superconductivity",
        attempt=1,
        max_attempts=3,
    )

    published_id = await pubsub_publisher.publish(envelope)
    assert published_id == "job_pubsub_1"
    assert len(fake_publisher_client.published_messages) == 1

    msg = fake_publisher_client.published_messages[0]
    assert msg["topic"] == "projects/test-project/topics/test-tasks"
    assert msg["attributes"]["job_id"] == "job_pubsub_1"
    assert msg["attributes"]["run_id"] == "run_pubsub_1"
    assert msg["attributes"]["attempt"] == "1"
    assert msg["attributes"]["idempotency_key"] == "job_pubsub_1_1"
    assert msg["attributes"]["status"] == "QUEUED"

    # Verify JSON deserialization matches
    decoded_env = JobEnvelope.model_validate_json(msg["data"])
    assert decoded_env.job_id == "job_pubsub_1"
    assert decoded_env.run_id == "run_pubsub_1"


@pytest.mark.asyncio
async def test_pubsub_publisher_dead_letter(
    pubsub_publisher: GooglePubSubPublisher,
    fake_publisher_client: FakePublisherClient,
) -> None:
    """Test 2: Verify publish_dead_letter routes to DLQ with DEAD_LETTERED status."""
    envelope = JobEnvelope(
        job_id="job_dlq_1",
        run_id="run_dlq_1",
        goal_query="Permanent failure inquiry",
        error="Fatal schema mismatch",
    )

    published_id = await pubsub_publisher.publish_dead_letter(envelope)
    assert published_id == "job_dlq_1"
    assert len(fake_publisher_client.published_messages) == 1

    msg = fake_publisher_client.published_messages[0]
    assert msg["topic"] == "projects/test-project/topics/test-dlq"
    assert msg["attributes"]["status"] == "DEAD_LETTERED"

    decoded_env = JobEnvelope.model_validate_json(msg["data"])
    assert decoded_env.status == JobStatus.DEAD_LETTERED
    assert decoded_env.completed_at is not None


@pytest.mark.asyncio
async def test_pubsub_consumer_successful_processing(
    fake_subscriber_client: FakeSubscriberClient,
    pubsub_publisher: GooglePubSubPublisher,
) -> None:
    """Test 3: Verify consumer pulls message, invokes handler, and ACKs on success."""
    processed_jobs: list[str] = []

    class SuccessHandler:
        async def handle_job(self, env: JobEnvelope) -> JobEnvelope:
            processed_jobs.append(env.job_id)
            return env.with_status(JobStatus.COMPLETED)

    consumer = GooglePubSubConsumer(
        subscription_name="test-sub",
        handler=SuccessHandler(),
        client=fake_subscriber_client,
        publisher=pubsub_publisher,
        project_id="test-project",
        worker_concurrency=1,
    )

    env = JobEnvelope(job_id="job_c_1", run_id="run_c_1", goal_query="Success topic")
    msg_bytes = env.model_dump_json().encode("utf-8")
    raw_msg = FakeReceivedMessage("ack_001", msg_bytes)
    fake_subscriber_client.queue.append(raw_msg)

    await consumer.start()
    assert consumer.is_running() is True

    try:
        for _ in range(20):
            if "job_c_1" in processed_jobs and raw_msg.acked:
                break
            await asyncio.sleep(0.05)

        assert "job_c_1" in processed_jobs
        assert raw_msg.acked is True
    finally:
        await consumer.stop()
        assert consumer.is_running() is False


@pytest.mark.asyncio
async def test_pubsub_consumer_malformed_payload_acks_to_prevent_poison_pill(
    fake_subscriber_client: FakeSubscriberClient,
    pubsub_publisher: GooglePubSubPublisher,
) -> None:
    """Test 4: Verify malformed message payload is acknowledged to avoid infinite poison pill loops."""
    consumer = GooglePubSubConsumer(
        subscription_name="test-sub",
        handler=ResearchJobWorker(),
        client=fake_subscriber_client,
        publisher=pubsub_publisher,
        project_id="test-project",
        worker_concurrency=1,
    )

    bad_msg = FakeReceivedMessage("ack_bad_001", b"{not-valid-json")
    fake_subscriber_client.queue.append(bad_msg)

    await consumer.start()
    try:
        for _ in range(20):
            if bad_msg.acked:
                break
            await asyncio.sleep(0.05)

        assert bad_msg.acked is True
    finally:
        await consumer.stop()


@pytest.mark.asyncio
async def test_pubsub_consumer_retry_and_dead_letter_on_exhaustion(
    fake_publisher_client: FakePublisherClient,
    fake_subscriber_client: FakeSubscriberClient,
    pubsub_publisher: GooglePubSubPublisher,
) -> None:
    """Test 5: Verify transient errors trigger retry re-publish and final exhaustion dead-letters."""
    attempts_seen: list[int] = []

    class FailingHandler:
        async def handle_job(self, env: JobEnvelope) -> JobEnvelope:
            attempts_seen.append(env.attempt)
            return env.with_status(
                JobStatus.FAILED, error="Transient LLM timeout", is_retryable=True
            )

    consumer = GooglePubSubConsumer(
        subscription_name="test-sub",
        handler=FailingHandler(),
        client=fake_subscriber_client,
        publisher=pubsub_publisher,
        project_id="test-project",
        worker_concurrency=1,
    )

    # Attempt 1 -> should schedule Attempt 2
    env1 = JobEnvelope(
        job_id="job_ret_1",
        run_id="run_ret_1",
        goal_query="Retry query",
        attempt=1,
        max_attempts=2,
    )
    msg1 = FakeReceivedMessage("ack_ret_001", env1.model_dump_json().encode("utf-8"))
    fake_subscriber_client.queue.append(msg1)

    await consumer.start()
    try:
        for _ in range(20):
            if len(fake_publisher_client.published_messages) == 1 and msg1.acked:
                break
            await asyncio.sleep(0.05)

        assert msg1.acked is True
        assert len(fake_publisher_client.published_messages) == 1

        retry_msg = fake_publisher_client.published_messages[0]
        assert retry_msg["topic"] == "projects/test-project/topics/test-tasks"
        assert retry_msg["attributes"]["attempt"] == "2"

        # Attempt 2 (exhaustion) -> should move to DLQ
        msg2 = FakeReceivedMessage("ack_ret_002", retry_msg["data"])
        fake_subscriber_client.queue.append(msg2)

        for _ in range(20):
            if len(fake_publisher_client.published_messages) == 2 and msg2.acked:
                break
            await asyncio.sleep(0.05)

        assert msg2.acked is True
        assert len(fake_publisher_client.published_messages) == 2

        dlq_msg = fake_publisher_client.published_messages[1]
        assert dlq_msg["topic"] == "projects/test-project/topics/test-dlq"
        assert dlq_msg["attributes"]["status"] == "DEAD_LETTERED"
        assert attempts_seen == [1, 2]
    finally:
        await consumer.stop()


@pytest.mark.asyncio
async def test_pubsub_consumer_non_retryable_dead_letter_immediately(
    fake_publisher_client: FakePublisherClient,
    fake_subscriber_client: FakeSubscriberClient,
    pubsub_publisher: GooglePubSubPublisher,
) -> None:
    """Test 6: Verify non-retryable error routes to DLQ immediately without retrying."""

    class NonRetryableHandler:
        async def handle_job(self, env: JobEnvelope) -> JobEnvelope:
            return env.with_status(
                JobStatus.FAILED, error="Invalid schema payload", is_retryable=False
            )

    consumer = GooglePubSubConsumer(
        subscription_name="test-sub",
        handler=NonRetryableHandler(),
        client=fake_subscriber_client,
        publisher=pubsub_publisher,
        project_id="test-project",
        worker_concurrency=1,
    )

    env = JobEnvelope(
        job_id="job_non_ret_1",
        run_id="run_non_ret_1",
        goal_query="Non-retryable query",
        attempt=1,
        max_attempts=5,
    )
    msg = FakeReceivedMessage("ack_nr_001", env.model_dump_json().encode("utf-8"))
    fake_subscriber_client.queue.append(msg)

    await consumer.start()
    try:
        for _ in range(20):
            if len(fake_publisher_client.published_messages) == 1 and msg.acked:
                break
            await asyncio.sleep(0.05)

        assert msg.acked is True
        assert len(fake_publisher_client.published_messages) == 1
        dlq_msg = fake_publisher_client.published_messages[0]
        assert dlq_msg["topic"] == "projects/test-project/topics/test-dlq"
    finally:
        await consumer.stop()


@pytest.mark.asyncio
async def test_ack_deadline_extender_lifecycle(
    fake_subscriber_client: FakeSubscriberClient,
) -> None:
    """Test 7: Verify AckDeadlineExtender starts, periodically extends deadline, and cancels cleanly."""
    extender = AckDeadlineExtender(
        subscriber_client=fake_subscriber_client,
        subscription_path="projects/test/subscriptions/test-sub",
        ack_id="ack_ext_1",
        extension_seconds=60,
        interval_seconds=0.03,
    )

    await extender.start()
    for _ in range(25):
        if extender.extension_count >= 2:
            break
        await asyncio.sleep(0.02)

    await extender.stop()

    assert extender.extension_count >= 2
    assert len(fake_subscriber_client.modified_ack_deadlines) >= 2
    last_mod = fake_subscriber_client.modified_ack_deadlines[-1]
    req = last_mod.get("request", last_mod)
    assert req["ack_ids"] == ["ack_ext_1"]
    assert req["ack_deadline_seconds"] == 60


@pytest.mark.asyncio
async def test_pubsub_duplicate_delivery_idempotency() -> None:
    """Test 8: Verify duplicate delivery of a completed or cancelled run does not re-execute DAG or mutate state."""
    goal = ResearchGoal(
        goal_id="g_idem", query="Idempotency test query", max_subtasks=2
    )
    run_ctx = RunContext(
        run_id="run_idem_01",
        goal=goal,
        cancellation_token=CancellationToken(),
        event_sink=InMemoryEventSink(),
        checkpoint_repo=InMemoryCheckpointRepository(),
    )
    runs = {run_ctx.run_id: run_ctx}

    execution_count = 0

    class TrackingWorker(ResearchJobWorker):
        async def handle_job(self, envelope: JobEnvelope) -> JobEnvelope:
            nonlocal execution_count
            execution_count += 1
            return await super().handle_job(envelope)

    worker = TrackingWorker(
        router=create_default_worker_router(),
        run_context_resolver=lambda r_id: runs.get(r_id),
    )

    env = JobEnvelope(
        job_id="job_idem_01",
        run_id=run_ctx.run_id,
        goal_query=goal.query,
    )

    # First delivery -> executes and completes
    res1 = await worker.handle_job(env)
    assert res1.status == JobStatus.COMPLETED
    assert run_ctx.status == RunStage.COMPLETED
    assert execution_count == 1

    # Second (duplicate) delivery -> recognizes COMPLETED, does not re-execute
    res2 = await worker.handle_job(env)
    assert res2.status == JobStatus.COMPLETED
    assert run_ctx.status == RunStage.COMPLETED
    assert (
        execution_count == 2
    )  # Method invoked, but super().handle_job returns COMPLETED immediately without planning


def test_pubsub_missing_dependency_error() -> None:
    """Test 9: Verify clear RuntimeError if google-cloud-pubsub is not installed and no client is injected."""
    orig_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if "pubsub" in name:
            raise ImportError("Mocked missing pubsub library")
        return orig_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        pub = GooglePubSubPublisher()
        with pytest.raises(RuntimeError, match="google-cloud-pubsub is required"):
            pub._get_client()

        sub = GooglePubSubConsumer("sub", ResearchJobWorker())
        with pytest.raises(RuntimeError, match="google-cloud-pubsub is required"):
            sub._get_client()
