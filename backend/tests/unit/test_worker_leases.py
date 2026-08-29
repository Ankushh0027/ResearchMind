"""Unit tests for Phase 7.1 worker lease management, identity, and heartbeat lifecycle."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.jobs.heartbeat import WorkerHeartbeat
from app.jobs.lease import (
    InMemoryLeaseManager,
    generate_worker_id,
)
from app.persistence.in_memory import InMemoryRunRepository
from app.persistence.protocols import RunRecord
from app.state.models import ResearchGoal


def _utc_now() -> datetime:
    return datetime.now(UTC)


@pytest.fixture
def run_repo() -> InMemoryRunRepository:
    return InMemoryRunRepository()


@pytest.fixture
def lease_manager(run_repo: InMemoryRunRepository) -> InMemoryLeaseManager:
    return InMemoryLeaseManager(run_repo)


async def _create_sample_run(
    run_repo: InMemoryRunRepository, run_id: str = "run_test_lease_01"
) -> RunRecord:
    goal = ResearchGoal(
        goal_id=f"goal_{run_id}",
        query="Investigate zero-noise extrapolation techniques in quantum computing.",
        domain_tags=("quantum", "physics"),
    )
    record = RunRecord(
        run_id=run_id,
        goal=goal,
    )
    return await run_repo.create_run(record)


class TestWorkerIdentity:
    """Test worker identity generation."""

    def test_generate_worker_id_format(self) -> None:
        wid1 = generate_worker_id("worker")
        wid2 = generate_worker_id("worker")

        assert wid1.startswith("worker-")
        assert wid2.startswith("worker-")
        assert wid1 != wid2
        parts = wid1.split("-")
        assert len(parts) >= 4


class TestWorkerLeaseManager:
    """Test worker lease acquisition, renewal, release, and expiration semantics."""

    @pytest.mark.asyncio
    async def test_acquire_lease_success(
        self, lease_manager: InMemoryLeaseManager, run_repo: InMemoryRunRepository
    ) -> None:
        sample_run = await _create_sample_run(run_repo)
        lease = await lease_manager.acquire_lease(
            run_id=sample_run.run_id,
            worker_id="worker_alpha",
            duration_seconds=30.0,
        )
        assert lease is not None
        assert lease.run_id == sample_run.run_id
        assert lease.worker_id == "worker_alpha"
        assert lease.lease_id.startswith("lease_")
        assert lease.lease_expires_at > _utc_now()
        assert not lease.is_expired

    @pytest.mark.asyncio
    async def test_acquire_lease_conflict_unexpired(
        self, lease_manager: InMemoryLeaseManager, run_repo: InMemoryRunRepository
    ) -> None:
        sample_run = await _create_sample_run(run_repo)
        lease1 = await lease_manager.acquire_lease(
            run_id=sample_run.run_id,
            worker_id="worker_alpha",
            duration_seconds=60.0,
        )
        assert lease1 is not None

        # Worker Beta tries to acquire while lease1 is active
        lease2 = await lease_manager.acquire_lease(
            run_id=sample_run.run_id,
            worker_id="worker_beta",
            duration_seconds=60.0,
        )
        assert lease2 is None

    @pytest.mark.asyncio
    async def test_acquire_expired_lease_takeover(
        self,
        lease_manager: InMemoryLeaseManager,
        run_repo: InMemoryRunRepository,
    ) -> None:
        sample_run = await _create_sample_run(run_repo)
        # Simulate an expired lease on the record
        past_time = _utc_now() - timedelta(seconds=10)
        expired_record = sample_run.with_updates(
            worker_id="worker_crashed",
            lease_id="lease_stale_123",
            lease_acquired_at=past_time - timedelta(seconds=30),
            lease_expires_at=past_time,
            heartbeat_at=past_time,
        )
        await run_repo.update_run(expired_record)

        # Worker Beta should successfully reclaim the expired lease
        lease = await lease_manager.acquire_lease(
            run_id=sample_run.run_id,
            worker_id="worker_beta",
            duration_seconds=30.0,
        )
        assert lease is not None
        assert lease.worker_id == "worker_beta"
        assert lease.lease_id != "lease_stale_123"

    @pytest.mark.asyncio
    async def test_renew_lease_success(
        self, lease_manager: InMemoryLeaseManager, run_repo: InMemoryRunRepository
    ) -> None:
        sample_run = await _create_sample_run(run_repo)
        lease = await lease_manager.acquire_lease(
            run_id=sample_run.run_id,
            worker_id="worker_alpha",
            duration_seconds=10.0,
        )
        assert lease is not None

        renewed = await lease_manager.renew_lease(
            run_id=sample_run.run_id,
            worker_id="worker_alpha",
            lease_id=lease.lease_id,
            duration_seconds=40.0,
        )
        assert renewed is not None
        assert renewed.lease_id == lease.lease_id
        assert renewed.lease_expires_at > lease.lease_expires_at

    @pytest.mark.asyncio
    async def test_renew_lease_wrong_owner_or_lease_id(
        self, lease_manager: InMemoryLeaseManager, run_repo: InMemoryRunRepository
    ) -> None:
        sample_run = await _create_sample_run(run_repo)
        lease = await lease_manager.acquire_lease(
            run_id=sample_run.run_id,
            worker_id="worker_alpha",
            duration_seconds=30.0,
        )
        assert lease is not None

        # Wrong worker ID
        renew1 = await lease_manager.renew_lease(
            run_id=sample_run.run_id,
            worker_id="worker_imposter",
            lease_id=lease.lease_id,
        )
        assert renew1 is None

        # Wrong lease ID
        renew2 = await lease_manager.renew_lease(
            run_id=sample_run.run_id,
            worker_id="worker_alpha",
            lease_id="lease_bogus_999",
        )
        assert renew2 is None

    @pytest.mark.asyncio
    async def test_release_lease_success_and_wrong_owner(
        self,
        lease_manager: InMemoryLeaseManager,
        run_repo: InMemoryRunRepository,
    ) -> None:
        sample_run = await _create_sample_run(run_repo)
        lease = await lease_manager.acquire_lease(
            run_id=sample_run.run_id,
            worker_id="worker_alpha",
            duration_seconds=30.0,
        )
        assert lease is not None

        # Wrong worker cannot release
        released_wrong = await lease_manager.release_lease(
            run_id=sample_run.run_id,
            worker_id="worker_beta",
            lease_id=lease.lease_id,
        )
        assert not released_wrong

        # Correct worker releases
        released = await lease_manager.release_lease(
            run_id=sample_run.run_id,
            worker_id="worker_alpha",
            lease_id=lease.lease_id,
        )
        assert released

        # Verify lease is cleared on run record
        rec = await run_repo.get_run(sample_run.run_id)
        assert rec is not None
        assert rec.lease_id is None
        assert rec.worker_id is None
        assert rec.lease_expires_at is None

    @pytest.mark.asyncio
    async def test_get_lease(
        self, lease_manager: InMemoryLeaseManager, run_repo: InMemoryRunRepository
    ) -> None:
        sample_run = await _create_sample_run(run_repo)
        lease_before = await lease_manager.get_lease(sample_run.run_id)
        assert lease_before is None

        lease_acq = await lease_manager.acquire_lease(
            run_id=sample_run.run_id,
            worker_id="worker_alpha",
            duration_seconds=25.0,
        )
        assert lease_acq is not None

        lease_after = await lease_manager.get_lease(sample_run.run_id)
        assert lease_after is not None
        assert lease_after.lease_id == lease_acq.lease_id
        assert lease_after.worker_id == "worker_alpha"


class TestWorkerHeartbeat:
    """Test background worker heartbeat renewal and failure callbacks."""

    @pytest.mark.asyncio
    async def test_heartbeat_renewal_loop(
        self, lease_manager: InMemoryLeaseManager, run_repo: InMemoryRunRepository
    ) -> None:
        sample_run = await _create_sample_run(run_repo)
        lease = await lease_manager.acquire_lease(
            run_id=sample_run.run_id,
            worker_id="worker_alpha",
            duration_seconds=5.0,
        )
        assert lease is not None
        initial_expires = lease.lease_expires_at

        heartbeat = WorkerHeartbeat(
            lease_manager=lease_manager,
            run_id=sample_run.run_id,
            worker_id="worker_alpha",
            lease_id=lease.lease_id,
            interval_seconds=0.05,
            lease_duration_seconds=10.0,
        )

        assert not heartbeat.is_running
        heartbeat.start()
        assert heartbeat.is_running

        # Let heartbeat renew at least once
        await asyncio.sleep(0.15)

        current_lease = await lease_manager.get_lease(sample_run.run_id)
        assert current_lease is not None
        assert current_lease.lease_expires_at > initial_expires

        await heartbeat.stop()
        assert not heartbeat.is_running

    @pytest.mark.asyncio
    async def test_heartbeat_callback_on_lease_revoked(
        self,
        lease_manager: InMemoryLeaseManager,
        run_repo: InMemoryRunRepository,
    ) -> None:
        sample_run = await _create_sample_run(run_repo)
        lease = await lease_manager.acquire_lease(
            run_id=sample_run.run_id,
            worker_id="worker_alpha",
            duration_seconds=30.0,
        )
        assert lease is not None

        lost_callback_called = False

        def _on_lost() -> None:
            nonlocal lost_callback_called
            lost_callback_called = True

        heartbeat = WorkerHeartbeat(
            lease_manager=lease_manager,
            run_id=sample_run.run_id,
            worker_id="worker_alpha",
            lease_id=lease.lease_id,
            interval_seconds=0.05,
            lease_duration_seconds=10.0,
            on_lease_lost=_on_lost,
        )
        heartbeat.start()

        # Simulate external lease takeover/invalidation
        rec = await run_repo.get_run(sample_run.run_id)
        assert rec is not None
        await run_repo.update_run(
            rec.with_updates(worker_id="worker_other", lease_id="lease_other")
        )

        await asyncio.sleep(0.15)
        await heartbeat.stop()

        assert lost_callback_called
