"""Unit tests for asynchronous job contracts, models, and protocols."""

import pytest
from pydantic import ValidationError

from app.jobs.protocols import (
    JobConsumerProtocol,
    JobEnvelope,
    JobHandlerProtocol,
    JobPublisherProtocol,
    JobStatus,
)


def test_job_envelope_creation_defaults() -> None:
    """Test 1: Verify JobEnvelope instantiates with expected defaults."""
    envelope = JobEnvelope(
        job_id="job_001",
        run_id="run_001",
        goal_query="Investigate quantum hall effect edge states.",
    )
    assert envelope.job_id == "job_001"
    assert envelope.run_id == "run_001"
    assert envelope.status == JobStatus.QUEUED
    assert envelope.attempt == 1
    assert envelope.max_attempts == 3
    assert envelope.is_retryable is True
    assert envelope.created_at is not None
    assert envelope.started_at is None
    assert envelope.completed_at is None
    assert envelope.error is None


def test_job_envelope_immutability_and_transition() -> None:
    """Test 2: Verify JobEnvelope is frozen and with_status produces immutable updates."""
    envelope = JobEnvelope(
        job_id="job_002",
        run_id="run_002",
        goal_query="Topological insulators.",
    )
    with pytest.raises(ValidationError):
        envelope.status = JobStatus.RUNNING

    running = envelope.with_status(JobStatus.RUNNING)
    assert running.status == JobStatus.RUNNING
    assert envelope.status == JobStatus.QUEUED  # original unchanged

    failed = running.with_status(
        JobStatus.FAILED, error="Network timeout", is_retryable=True
    )
    assert failed.status == JobStatus.FAILED
    assert failed.error == "Network timeout"
    assert failed.is_retryable is True


def test_job_envelope_validation_constraints() -> None:
    """Test 3: Verify validation rejects short query and invalid attempts."""
    with pytest.raises(ValidationError):
        JobEnvelope(
            job_id="job_003",
            run_id="run_003",
            goal_query="ab",  # min_length=3
        )

    with pytest.raises(ValidationError):
        JobEnvelope(
            job_id="job_004",
            run_id="run_004",
            goal_query="Valid goal inquiry",
            attempt=0,  # ge=1
        )

    with pytest.raises(ValidationError):
        JobEnvelope(
            job_id="job_005",
            run_id="run_005",
            goal_query="Valid goal inquiry",
            max_attempts=0,  # ge=1
        )


def test_job_envelope_extra_forbid() -> None:
    """Test 4: Verify extra fields are forbidden."""
    with pytest.raises(ValidationError):
        JobEnvelope(
            job_id="job_006",
            run_id="run_006",
            goal_query="Valid goal inquiry",
            unexpected_field="disallowed",  # type: ignore[call-arg]
        )


def test_job_protocols_runtime_checkable() -> None:
    """Test 5: Verify protocol runtime checks work as expected."""

    class DummyPublisher:
        async def publish(self, envelope: JobEnvelope) -> str:
            return envelope.job_id

    class DummyHandler:
        async def handle_job(self, envelope: JobEnvelope) -> JobEnvelope:
            return envelope

    class DummyConsumer:
        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        def is_running(self) -> bool:
            return True

    assert isinstance(DummyPublisher(), JobPublisherProtocol)
    assert isinstance(DummyHandler(), JobHandlerProtocol)
    assert isinstance(DummyConsumer(), JobConsumerProtocol)
