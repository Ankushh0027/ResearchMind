"""Google Cloud Pub/Sub transport implementation for distributed job execution."""

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from app.jobs.protocols import (
    JobConsumerProtocol,
    JobEnvelope,
    JobHandlerProtocol,
    JobPublisherProtocol,
    JobStatus,
)

logger = logging.getLogger("researchmind.jobs.pubsub")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _create_publisher_client(
    project_id: str | None = None, emulator_host: str | None = None
) -> Any:
    """Instantiate Google Cloud Pub/Sub PublisherClient with emulator support."""
    _ = project_id
    try:
        from google.cloud import pubsub_v1

        if emulator_host:
            import os

            os.environ["PUBSUB_EMULATOR_HOST"] = emulator_host

        return pubsub_v1.PublisherClient()
    except ImportError as e:
        raise RuntimeError(
            "google-cloud-pubsub is required for Pub/Sub transport. "
            "Install with: pip install google-cloud-pubsub"
        ) from e


def _create_subscriber_client(
    project_id: str | None = None, emulator_host: str | None = None
) -> Any:
    """Instantiate Google Cloud Pub/Sub SubscriberClient with emulator support."""
    _ = project_id
    try:
        from google.cloud import pubsub_v1

        if emulator_host:
            import os

            os.environ["PUBSUB_EMULATOR_HOST"] = emulator_host

        return pubsub_v1.SubscriberClient()
    except ImportError as e:
        raise RuntimeError(
            "google-cloud-pubsub is required for Pub/Sub transport. "
            "Install with: pip install google-cloud-pubsub"
        ) from e


class AckDeadlineExtender:
    """Background lease-extension heartbeat periodically extending Pub/Sub acknowledgement deadlines."""

    def __init__(
        self,
        subscriber_client: Any,
        subscription_path: str,
        ack_id: str,
        extension_seconds: int = 60,
        interval_seconds: float = 20.0,
    ) -> None:
        self._subscriber = subscriber_client
        self._subscription_path = subscription_path
        self._ack_id = ack_id
        self._extension_seconds = max(10, min(600, extension_seconds))
        self._interval_seconds = max(0.1, interval_seconds)
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._extension_count = 0

    @property
    def extension_count(self) -> int:
        """Return how many times deadline was extended."""
        return self._extension_count

    async def start(self) -> None:
        """Start the background lease-extension heartbeat loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._heartbeat_loop())

    async def stop(self) -> None:
        """Stop the heartbeat loop and ensure background task is cancelled cleanly."""
        if not self._running:
            return
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _heartbeat_loop(self) -> None:
        """Periodically call modify_ack_deadline on the subscriber client."""
        while self._running:
            try:
                await asyncio.sleep(self._interval_seconds)
                if not self._running:
                    break

                await self._extend_deadline()
                self._extension_count += 1
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(
                    "Failed to extend Pub/Sub ack deadline for ack_id %s: %s",
                    self._ack_id,
                    e,
                )

    async def _extend_deadline(self) -> None:
        """Perform modify_ack_deadline asynchronously."""
        if hasattr(self._subscriber, "modify_ack_deadline"):
            func = self._subscriber.modify_ack_deadline
            kwargs = {
                "request": {
                    "subscription": self._subscription_path,
                    "ack_ids": [self._ack_id],
                    "ack_deadline_seconds": self._extension_seconds,
                }
            }
            if asyncio.iscoroutinefunction(func):
                await func(**kwargs)
            else:
                try:
                    await asyncio.to_thread(func, **kwargs)
                except TypeError:
                    # Fallback for mock/clients taking positional/keyword variations
                    await asyncio.to_thread(
                        func,
                        subscription=self._subscription_path,
                        ack_ids=[self._ack_id],
                        ack_deadline_seconds=self._extension_seconds,
                    )


class GooglePubSubPublisher(JobPublisherProtocol):
    """Google Cloud Pub/Sub implementation of JobPublisherProtocol."""

    def __init__(
        self,
        client: Any = None,
        project_id: str = "researchmind-dev",
        topic_name: str = "researchmind-agent-tasks",
        dead_letter_topic_name: str | None = "researchmind-agent-tasks-dlq",
        emulator_host: str | None = None,
    ) -> None:
        self._client = client
        self._project_id = project_id
        self._topic_name = topic_name
        self._dead_letter_topic_name = dead_letter_topic_name
        self._emulator_host = emulator_host

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        self._client = _create_publisher_client(
            project_id=self._project_id, emulator_host=self._emulator_host
        )
        return self._client

    def _format_topic_path(self, topic: str) -> str:
        if topic.startswith("projects/"):
            return topic
        return f"projects/{self._project_id}/topics/{topic}"

    @property
    def topic_path(self) -> str:
        """Return the fully qualified Pub/Sub topic path for standard tasks."""
        return self._format_topic_path(self._topic_name)

    @property
    def dead_letter_topic_path(self) -> str | None:
        """Return the fully qualified Pub/Sub topic path for dead-letter tasks if configured."""
        if not self._dead_letter_topic_name:
            return None
        return self._format_topic_path(self._dead_letter_topic_name)

    async def publish(self, envelope: JobEnvelope) -> str:
        """Publish a research job envelope to the configured Pub/Sub topic."""
        queued_envelope = (
            envelope
            if envelope.status == JobStatus.QUEUED
            else envelope.with_status(JobStatus.QUEUED)
        )
        return await self._publish_to_topic(self.topic_path, queued_envelope)

    async def publish_dead_letter(self, envelope: JobEnvelope) -> str:
        """Publish an unrecoverable job envelope to the dead-letter topic."""
        target_path = self.dead_letter_topic_path or self.topic_path
        dead_envelope = envelope.with_status(
            JobStatus.DEAD_LETTERED, completed_at=_utc_now()
        )
        return await self._publish_to_topic(target_path, dead_envelope)

    async def _publish_to_topic(self, topic_path: str, envelope: JobEnvelope) -> str:
        client = self._get_client()
        payload = envelope.model_dump_json().encode("utf-8")
        attributes = {
            "job_id": str(envelope.job_id),
            "run_id": str(envelope.run_id),
            "attempt": str(envelope.attempt),
            "idempotency_key": f"{envelope.job_id}_{envelope.attempt}",
            "status": str(envelope.status.value),
        }

        func = client.publish
        if asyncio.iscoroutinefunction(func):
            res = await func(topic_path, data=payload, **attributes)
        else:
            # Synchronous / thread-based publish returning Future
            future = await asyncio.to_thread(
                func, topic_path, data=payload, **attributes
            )
            if hasattr(future, "result"):
                if asyncio.iscoroutinefunction(future.result):
                    res = await future.result()
                else:
                    res = await asyncio.to_thread(future.result)
            else:
                res = future

        logger.debug(
            "Published job envelope %s to %s (message_id: %s)",
            envelope.job_id,
            topic_path,
            res,
        )
        return str(envelope.job_id)


class GooglePubSubConsumer(JobConsumerProtocol):
    """Google Cloud Pub/Sub implementation of JobConsumerProtocol."""

    def __init__(
        self,
        subscription_name: str,
        handler: JobHandlerProtocol,
        client: Any = None,
        project_id: str = "researchmind-dev",
        publisher: GooglePubSubPublisher | None = None,
        dead_letter_topic_name: str | None = "researchmind-agent-tasks-dlq",
        worker_concurrency: int = 2,
        ack_deadline_seconds: int = 60,
        ack_extension_seconds: int = 60,
        heartbeat_interval_seconds: float = 20.0,
        emulator_host: str | None = None,
    ) -> None:
        self._subscription_name = subscription_name
        self._handler = handler
        self._client = client
        self._project_id = project_id
        self._publisher = publisher
        self._dead_letter_topic_name = dead_letter_topic_name
        self._worker_concurrency = max(1, worker_concurrency)
        self._ack_deadline_seconds = ack_deadline_seconds
        self._ack_extension_seconds = ack_extension_seconds
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._emulator_host = emulator_host
        self._running = False
        self._tasks: list[asyncio.Task[Any]] = []
        self._stop_event = asyncio.Event()

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        self._client = _create_subscriber_client(
            project_id=self._project_id, emulator_host=self._emulator_host
        )
        return self._client

    def _format_subscription_path(self, sub: str) -> str:
        if sub.startswith("projects/"):
            return sub
        return f"projects/{self._project_id}/subscriptions/{sub}"

    @property
    def subscription_path(self) -> str:
        """Return the fully qualified Pub/Sub subscription path."""
        return self._format_subscription_path(self._subscription_name)

    async def start(self) -> None:
        """Start the background Pub/Sub consumer worker loop tasks."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._tasks = [
            asyncio.create_task(self._worker_loop(i))
            for i in range(self._worker_concurrency)
        ]
        logger.info(
            "Started GooglePubSubConsumer pool (%d workers) on %s",
            self._worker_concurrency,
            self.subscription_path,
        )

    async def stop(self) -> None:
        """Gracefully stop background Pub/Sub consumer tasks."""
        if not self._running:
            return
        self._running = False
        self._stop_event.set()

        for task in self._tasks:
            task.cancel()

        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("Stopped GooglePubSubConsumer gracefully.")

    def is_running(self) -> bool:
        """Return whether the consumer worker pool is active."""
        return self._running

    async def _worker_loop(self, _worker_idx: int) -> None:
        """Worker loop continuously pulling messages, extending lease, and invoking handler."""
        client = self._get_client()

        while self._running:
            try:
                # Pull messages asynchronously with short timeout to stay responsive to shutdown
                messages = await self._pull_messages(client, max_messages=1)
                if not messages:
                    await asyncio.sleep(0.2)
                    continue

                for message in messages:
                    if not self._running:
                        # Requeue / Nack message if stopping
                        await self._nack_message(client, message)
                        break
                    await self._process_message(client, message)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Pub/Sub pull exception in worker %d: %s", _worker_idx, e)
                await asyncio.sleep(0.5)

    async def _pull_messages(self, client: Any, max_messages: int = 1) -> list[Any]:
        """Pull messages from Pub/Sub subscription."""
        sub_path = self.subscription_path
        if hasattr(client, "pull"):
            func = client.pull
            kwargs = {
                "request": {
                    "subscription": sub_path,
                    "max_messages": max_messages,
                }
            }
            try:
                if asyncio.iscoroutinefunction(func):
                    response = await func(**kwargs)
                else:
                    try:
                        response = await asyncio.to_thread(func, **kwargs)
                    except TypeError:
                        response = await asyncio.to_thread(
                            func,
                            subscription=sub_path,
                            max_messages=max_messages,
                        )
            except Exception:
                return []

            if hasattr(response, "received_messages"):
                return list(response.received_messages)
            if isinstance(response, list):
                return response
        return []

    async def _process_message(self, client: Any, message: Any) -> None:
        """Process a single pulled Pub/Sub message with lease extension, error handling, and retry/DLQ."""
        ack_id = getattr(message, "ack_id", None)
        raw_msg = getattr(message, "message", message)
        data = getattr(raw_msg, "data", b"")
        if isinstance(data, str):
            data = data.encode("utf-8")

        # 1. Start lease extension heartbeat if ack_id exists
        extender: AckDeadlineExtender | None = None
        if ack_id:
            extender = AckDeadlineExtender(
                subscriber_client=client,
                subscription_path=self.subscription_path,
                ack_id=ack_id,
                extension_seconds=self._ack_extension_seconds,
                interval_seconds=self._heartbeat_interval_seconds,
            )
            await extender.start()

        try:
            # 2. Deserialize and validate JobEnvelope
            try:
                envelope = JobEnvelope.model_validate_json(data)
            except (ValidationError, Exception) as val_err:
                logger.error(
                    "Malformed JobEnvelope payload received on %s: %s. Acknowledging to avoid poison pill.",
                    self.subscription_path,
                    val_err,
                )
                await self._ack_message(client, message)
                return

            # 3. Mark RUNNING and invoke handler
            running_envelope = envelope.with_status(
                JobStatus.RUNNING, started_at=_utc_now()
            )
            try:
                result_envelope = await self._handler.handle_job(running_envelope)
            except Exception as e:
                result_envelope = running_envelope.with_status(
                    JobStatus.FAILED,
                    error=str(e),
                    is_retryable=True,
                    completed_at=_utc_now(),
                )

            # 4. Handle results according to status
            if result_envelope.status in (JobStatus.COMPLETED, JobStatus.CANCELLED):
                await self._ack_message(client, message)
                logger.info(
                    "Job %s reached %s. Message acknowledged.",
                    result_envelope.job_id,
                    result_envelope.status,
                )

            elif result_envelope.status == JobStatus.FAILED:
                if (
                    result_envelope.is_retryable
                    and result_envelope.attempt < result_envelope.max_attempts
                ):
                    # Transient failure with remaining attempts -> Retry
                    next_attempt = result_envelope.attempt + 1
                    retry_envelope = result_envelope.with_status(
                        JobStatus.QUEUED,
                        attempt=next_attempt,
                        started_at=None,
                        completed_at=None,
                    )
                    logger.warning(
                        "Job %s failed (attempt %d/%d): %s. Scheduling retry.",
                        result_envelope.job_id,
                        result_envelope.attempt,
                        result_envelope.max_attempts,
                        result_envelope.error,
                    )

                    if self._publisher is not None:
                        await self._publisher.publish(retry_envelope)
                        await self._ack_message(client, message)
                    else:
                        # If no publisher injected, NACK message for Pub/Sub redelivery
                        await self._nack_message(client, message)
                else:
                    # Retry exhausted or non-retryable error -> Dead-letter
                    logger.error(
                        "Job %s failed permanently (attempt %d/%d, retryable=%s): %s. Moving to dead-letter.",
                        result_envelope.job_id,
                        result_envelope.attempt,
                        result_envelope.max_attempts,
                        result_envelope.is_retryable,
                        result_envelope.error,
                    )
                    if self._publisher is not None and self._dead_letter_topic_name:
                        await self._publisher.publish_dead_letter(result_envelope)

                    await self._ack_message(client, message)

        finally:
            if extender is not None:
                await extender.stop()

    async def _ack_message(self, client: Any, message: Any) -> None:
        """Acknowledge a Pub/Sub message."""
        if hasattr(message, "ack"):
            func = message.ack
            if asyncio.iscoroutinefunction(func):
                await func()
            else:
                await asyncio.to_thread(func)
            return

        ack_id = getattr(message, "ack_id", None)
        if ack_id and hasattr(client, "acknowledge"):
            func = client.acknowledge
            kwargs = {
                "request": {
                    "subscription": self.subscription_path,
                    "ack_ids": [ack_id],
                }
            }
            if asyncio.iscoroutinefunction(func):
                await func(**kwargs)
            else:
                try:
                    await asyncio.to_thread(func, **kwargs)
                except TypeError:
                    await asyncio.to_thread(
                        func, subscription=self.subscription_path, ack_ids=[ack_id]
                    )

    async def _nack_message(self, client: Any, message: Any) -> None:
        """Negative acknowledge / reset ack deadline for a Pub/Sub message."""
        if hasattr(message, "nack"):
            func = message.nack
            if asyncio.iscoroutinefunction(func):
                await func()
            else:
                await asyncio.to_thread(func)
            return

        ack_id = getattr(message, "ack_id", None)
        if ack_id and hasattr(client, "modify_ack_deadline"):
            func = client.modify_ack_deadline
            kwargs = {
                "request": {
                    "subscription": self.subscription_path,
                    "ack_ids": [ack_id],
                    "ack_deadline_seconds": 0,
                }
            }
            if asyncio.iscoroutinefunction(func):
                await func(**kwargs)
            else:
                try:
                    await asyncio.to_thread(func, **kwargs)
                except TypeError:
                    await asyncio.to_thread(
                        func,
                        subscription=self.subscription_path,
                        ack_ids=[ack_id],
                        ack_deadline_seconds=0,
                    )


__all__ = [
    "AckDeadlineExtender",
    "GooglePubSubConsumer",
    "GooglePubSubPublisher",
]
