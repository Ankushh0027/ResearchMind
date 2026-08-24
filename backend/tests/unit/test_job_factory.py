import pytest

from app.config.settings import AppSettings
from app.jobs.factory import (
    create_job_consumer,
    create_job_publisher,
)
from app.jobs.in_memory import (
    InMemoryJobConsumer,
    InMemoryJobPublisher,
    InMemoryJobQueue,
)
from app.jobs.protocols import JobEnvelope
from app.jobs.pubsub import (
    GooglePubSubConsumer,
    GooglePubSubPublisher,
)


class DummyHandler:
    async def handle_job(self, envelope: JobEnvelope) -> JobEnvelope:
        return envelope


def test_create_job_publisher_in_memory_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test 1: Verify default factory creates InMemoryJobPublisher."""
    monkeypatch.setenv("JOB_TRANSPORT", "in_memory")
    settings = AppSettings()
    queue = InMemoryJobQueue()
    publisher = create_job_publisher(settings=settings, queue=queue)
    assert isinstance(publisher, InMemoryJobPublisher)


def test_create_job_publisher_pubsub(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test 2: Verify factory creates GooglePubSubPublisher when job_transport is pubsub."""
    monkeypatch.setenv("JOB_TRANSPORT", "pubsub")
    monkeypatch.setenv("GCP_PROJECT_ID", "test-proj-pub")
    monkeypatch.setenv("PUBSUB_TASKS_TOPIC", "tasks-topic-custom")
    monkeypatch.setenv("PUBSUB_DEAD_LETTER_TOPIC", "tasks-dlq-custom")

    settings = AppSettings()
    publisher = create_job_publisher(settings=settings)
    assert isinstance(publisher, GooglePubSubPublisher)
    assert publisher.topic_path == "projects/test-proj-pub/topics/tasks-topic-custom"
    assert (
        publisher.dead_letter_topic_path
        == "projects/test-proj-pub/topics/tasks-dlq-custom"
    )


def test_create_job_consumer_in_memory_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test 3: Verify default factory creates InMemoryJobConsumer."""
    monkeypatch.setenv("JOB_TRANSPORT", "in_memory")
    settings = AppSettings()
    queue = InMemoryJobQueue()
    consumer = create_job_consumer(
        handler=DummyHandler(), settings=settings, queue=queue
    )
    assert isinstance(consumer, InMemoryJobConsumer)


def test_create_job_consumer_pubsub(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test 4: Verify factory creates GooglePubSubConsumer when job_transport is pubsub."""
    monkeypatch.setenv("JOB_TRANSPORT", "pubsub")
    monkeypatch.setenv("GCP_PROJECT_ID", "test-proj-sub")
    monkeypatch.setenv("PUBSUB_TASKS_SUBSCRIPTION", "tasks-sub-custom")
    monkeypatch.setenv("PUBSUB_DEAD_LETTER_TOPIC", "tasks-dlq-custom")
    monkeypatch.setenv("PUBSUB_ACK_DEADLINE_SECONDS", "120")
    monkeypatch.setenv("PUBSUB_ACK_EXTENSION_SECONDS", "90")

    settings = AppSettings()
    consumer = create_job_consumer(handler=DummyHandler(), settings=settings)
    assert isinstance(consumer, GooglePubSubConsumer)
    assert (
        consumer.subscription_path
        == "projects/test-proj-sub/subscriptions/tasks-sub-custom"
    )
