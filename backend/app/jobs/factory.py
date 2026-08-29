"""Factory constructors for ResearchMind job publishers and consumers."""

from typing import Any

from app.config.settings import AppSettings, get_settings
from app.jobs.in_memory import (
    InMemoryJobConsumer,
    InMemoryJobPublisher,
    InMemoryJobQueue,
)
from app.jobs.protocols import (
    JobConsumerProtocol,
    JobHandlerProtocol,
    JobPublisherProtocol,
)
from app.jobs.pubsub import (
    GooglePubSubConsumer,
    GooglePubSubPublisher,
)


def create_job_publisher(
    settings: AppSettings | None = None,
    queue: InMemoryJobQueue | None = None,
    publisher_client: Any = None,
) -> JobPublisherProtocol:
    """Instantiate configured JobPublisherProtocol (InMemory or GooglePubSub)."""
    cfg = settings or get_settings()
    if cfg.job_transport == "pubsub":
        return GooglePubSubPublisher(
            client=publisher_client,
            project_id=cfg.gcp_project_id,
            topic_name=cfg.pubsub_tasks_topic,
            dead_letter_topic_name=cfg.pubsub_dead_letter_topic,
            emulator_host=cfg.pubsub_emulator_host,
        )
    return InMemoryJobPublisher(queue or InMemoryJobQueue())


def create_job_consumer(
    handler: JobHandlerProtocol,
    settings: AppSettings | None = None,
    queue: InMemoryJobQueue | None = None,
    subscriber_client: Any = None,
    publisher: GooglePubSubPublisher | None = None,
    publisher_client: Any = None,
) -> JobConsumerProtocol:
    """Instantiate configured JobConsumerProtocol (InMemory or GooglePubSub)."""
    cfg = settings or get_settings()
    if cfg.job_transport == "pubsub":
        active_publisher = publisher
        if active_publisher is None:
            pub_candidate = create_job_publisher(
                settings=cfg, publisher_client=publisher_client
            )
            if isinstance(pub_candidate, GooglePubSubPublisher):
                active_publisher = pub_candidate

        return GooglePubSubConsumer(
            subscription_name=cfg.pubsub_tasks_subscription,
            handler=handler,
            client=subscriber_client,
            project_id=cfg.gcp_project_id,
            publisher=active_publisher,
            dead_letter_topic_name=cfg.pubsub_dead_letter_topic,
            worker_concurrency=cfg.worker_concurrency,
            ack_deadline_seconds=cfg.pubsub_ack_deadline_seconds,
            ack_extension_seconds=cfg.pubsub_ack_extension_seconds,
            emulator_host=cfg.pubsub_emulator_host,
        )
    return InMemoryJobConsumer(
        queue=queue or InMemoryJobQueue(),
        handler=handler,
        worker_concurrency=cfg.worker_concurrency,
    )


def create_lease_manager(
    settings: AppSettings | None = None,
    run_repo: Any = None,
    firestore_client: Any = None,
) -> Any:
    """Instantiate configured LeaseManagerProtocol (InMemory or Firestore)."""
    cfg = settings or get_settings()
    if cfg.persistence_backend == "firestore":
        from app.jobs.lease import FirestoreLeaseManager

        return FirestoreLeaseManager(
            client=firestore_client,
            project_id=cfg.gcp_project_id,
            database=cfg.firestore_database,
            collection_name=cfg.firestore_runs_collection,
        )
    from app.jobs.lease import InMemoryLeaseManager
    from app.persistence.in_memory import InMemoryRunRepository

    return InMemoryLeaseManager(run_repo or InMemoryRunRepository())


__all__ = [
    "create_job_consumer",
    "create_job_publisher",
    "create_lease_manager",
]
