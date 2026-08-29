"""Worker lease models, protocol abstractions, and persistence implementations."""

import asyncio
import os
import socket
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from app.persistence.protocols import RunRecord, RunRepositoryProtocol


def _utc_now() -> datetime:
    return datetime.now(UTC)


def generate_worker_id(prefix: str = "worker") -> str:
    """Generate a unique, stable, PII-free worker process identifier."""
    hostname = socket.gethostname().split(".")[0] or "node"
    # Sanitize hostname to alphanumeric and hyphens
    sanitized_host = "".join(c if c.isalnum() or c == "-" else "_" for c in hostname)
    pid = os.getpid()
    unique_suffix = uuid.uuid4().hex[:8]
    return f"{prefix}-{sanitized_host}-{pid}-{unique_suffix}"


class WorkerLease(BaseModel):
    """Immutable model representing an active worker execution lease."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(..., description="Target research run identifier")
    worker_id: str = Field(..., description="Unique worker process identifier")
    lease_id: str = Field(..., description="Unique lease instance identifier")
    lease_acquired_at: datetime = Field(
        default_factory=_utc_now, description="Timestamp lease was acquired"
    )
    lease_expires_at: datetime = Field(
        ..., description="Timestamp after which lease is considered stale/expired"
    )
    heartbeat_at: datetime = Field(
        default_factory=_utc_now, description="Timestamp of latest lease heartbeat"
    )
    duration_seconds: float = Field(
        default=30.0, gt=0.0, description="Granted lease duration in seconds"
    )

    @property
    def is_expired(self) -> bool:
        """Return True if lease expiration timestamp is in the past."""
        return _utc_now() >= self.lease_expires_at


@runtime_checkable
class LeaseManagerProtocol(Protocol):
    """Protocol for acquiring, renewing, and releasing worker execution leases."""

    async def acquire_lease(
        self,
        run_id: str,
        worker_id: str,
        duration_seconds: float = 30.0,
    ) -> WorkerLease | None:
        """Attempt to acquire or reclaim an execution lease for a run.

        Returns WorkerLease if successfully acquired, or None if currently held by
        another active, unexpired worker.
        """
        ...

    async def renew_lease(
        self,
        run_id: str,
        worker_id: str,
        lease_id: str,
        duration_seconds: float = 30.0,
    ) -> WorkerLease | None:
        """Renew an existing active lease owned by the caller.

        Returns updated WorkerLease if renewed, or None if lease ownership was lost.
        """
        ...

    async def release_lease(
        self,
        run_id: str,
        worker_id: str,
        lease_id: str,
    ) -> bool:
        """Release an active lease upon clean completion, failure, or cancellation."""
        ...

    async def get_lease(self, run_id: str) -> WorkerLease | None:
        """Inspect current lease state for a run."""
        ...

    def is_lease_expired(self, lease: WorkerLease) -> bool:
        """Check whether a lease is expired relative to current UTC time."""
        ...


class InMemoryLeaseManager(LeaseManagerProtocol):
    """Deterministic, async-safe in-memory implementation of LeaseManagerProtocol."""

    def __init__(self, run_repo: RunRepositoryProtocol) -> None:
        self._run_repo = run_repo
        self._lock = asyncio.Lock()

    def is_lease_expired(self, lease: WorkerLease) -> bool:
        """Check if lease expiration timestamp is in the past."""
        return _utc_now() >= lease.lease_expires_at

    async def acquire_lease(
        self,
        run_id: str,
        worker_id: str,
        duration_seconds: float = 30.0,
    ) -> WorkerLease | None:
        """Atomically acquire or reclaim an expired lease."""
        async with self._lock:
            record = await self._run_repo.get_run(run_id)
            if record is None:
                return None

            now = _utc_now()
            # Lease is available if:
            # 1. No active lease exists (lease_expires_at is None or lease_id is None)
            # 2. Existing lease is expired (lease_expires_at <= now)
            # 3. Same worker is re-acquiring its own lease
            can_acquire = (
                record.lease_expires_at is None
                or record.lease_id is None
                or record.lease_expires_at <= now
                or record.worker_id == worker_id
            )

            if not can_acquire:
                return None

            new_lease_id = f"lease_{uuid.uuid4().hex[:12]}"
            expires_at = now + timedelta(seconds=duration_seconds)

            updated = record.with_updates(
                worker_id=worker_id,
                lease_id=new_lease_id,
                lease_acquired_at=now,
                lease_expires_at=expires_at,
                heartbeat_at=now,
            )
            await self._run_repo.update_run(updated)

            return WorkerLease(
                run_id=run_id,
                worker_id=worker_id,
                lease_id=new_lease_id,
                lease_acquired_at=now,
                lease_expires_at=expires_at,
                heartbeat_at=now,
                duration_seconds=duration_seconds,
            )

    async def renew_lease(
        self,
        run_id: str,
        worker_id: str,
        lease_id: str,
        duration_seconds: float = 30.0,
    ) -> WorkerLease | None:
        """Atomically renew lease if ownership is preserved."""
        async with self._lock:
            record = await self._run_repo.get_run(run_id)
            if record is None:
                return None

            if record.worker_id != worker_id or record.lease_id != lease_id:
                return None

            now = _utc_now()
            expires_at = now + timedelta(seconds=duration_seconds)

            updated = record.with_updates(
                heartbeat_at=now,
                lease_expires_at=expires_at,
            )
            await self._run_repo.update_run(updated)

            return WorkerLease(
                run_id=run_id,
                worker_id=worker_id,
                lease_id=lease_id,
                lease_acquired_at=record.lease_acquired_at or now,
                lease_expires_at=expires_at,
                heartbeat_at=now,
                duration_seconds=duration_seconds,
            )

    async def release_lease(
        self,
        run_id: str,
        worker_id: str,
        lease_id: str,
    ) -> bool:
        """Atomically release lease if owned by caller."""
        async with self._lock:
            record = await self._run_repo.get_run(run_id)
            if record is None:
                return False

            if record.worker_id != worker_id or record.lease_id != lease_id:
                return False

            updated = record.with_updates(clear_lease=True)
            await self._run_repo.update_run(updated)
            return True

    async def get_lease(self, run_id: str) -> WorkerLease | None:
        """Fetch current lease state for a run."""
        async with self._lock:
            record = await self._run_repo.get_run(run_id)
            if (
                record is None
                or record.lease_id is None
                or record.worker_id is None
                or record.lease_expires_at is None
            ):
                return None

            return WorkerLease(
                run_id=record.run_id,
                worker_id=record.worker_id,
                lease_id=record.lease_id,
                lease_acquired_at=record.lease_acquired_at or record.created_at,
                lease_expires_at=record.lease_expires_at,
                heartbeat_at=record.heartbeat_at or record.created_at,
                duration_seconds=max(
                    1.0,
                    (
                        record.lease_expires_at
                        - (record.lease_acquired_at or record.created_at)
                    ).total_seconds(),
                ),
            )


class FirestoreLeaseManager(LeaseManagerProtocol):
    """Google Cloud Firestore transactional implementation of LeaseManagerProtocol."""

    def __init__(
        self,
        client: Any = None,
        project_id: str | None = None,
        database: str = "(default)",
        collection_name: str = "research_runs",
    ) -> None:
        self._client = client
        self._project_id = project_id
        self._database = database
        self._collection_name = collection_name

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        from google.cloud import firestore

        self._client = firestore.AsyncClient(
            project=self._project_id, database=self._database
        )
        return self._client

    def is_lease_expired(self, lease: WorkerLease) -> bool:
        """Check if lease expiration timestamp is in the past."""
        return _utc_now() >= lease.lease_expires_at

    async def acquire_lease(
        self,
        run_id: str,
        worker_id: str,
        duration_seconds: float = 30.0,
    ) -> WorkerLease | None:
        """Acquire or reclaim lease using a Firestore transaction."""
        client = self._get_client()
        doc_ref = client.collection(self._collection_name).document(run_id)
        now = _utc_now()
        expires_at = now + timedelta(seconds=duration_seconds)
        new_lease_id = f"lease_{uuid.uuid4().hex[:12]}"

        from google.cloud import firestore

        transaction = client.transaction()

        @firestore.async_transactional
        async def _acquire_in_transaction(txn: Any) -> WorkerLease | None:
            snapshot = await doc_ref.get(transaction=txn)
            if not snapshot.exists:
                return None
            data = snapshot.to_dict() or {}
            record = RunRecord.model_validate(data)

            can_acquire = (
                record.lease_expires_at is None
                or record.lease_id is None
                or record.lease_expires_at <= now
                or record.worker_id == worker_id
            )
            if not can_acquire:
                return None

            updated = record.with_updates(
                worker_id=worker_id,
                lease_id=new_lease_id,
                lease_acquired_at=now,
                lease_expires_at=expires_at,
                heartbeat_at=now,
            )
            txn.set(doc_ref, updated.model_dump(mode="json"))
            return WorkerLease(
                run_id=run_id,
                worker_id=worker_id,
                lease_id=new_lease_id,
                lease_acquired_at=now,
                lease_expires_at=expires_at,
                heartbeat_at=now,
                duration_seconds=duration_seconds,
            )

        lease = await _acquire_in_transaction(transaction)
        return lease

    async def renew_lease(
        self,
        run_id: str,
        worker_id: str,
        lease_id: str,
        duration_seconds: float = 30.0,
    ) -> WorkerLease | None:
        """Renew active lease using a Firestore transaction."""
        client = self._get_client()
        doc_ref = client.collection(self._collection_name).document(run_id)
        now = _utc_now()
        expires_at = now + timedelta(seconds=duration_seconds)

        from google.cloud import firestore

        transaction = client.transaction()

        @firestore.async_transactional
        async def _renew_in_transaction(txn: Any) -> WorkerLease | None:
            snapshot = await doc_ref.get(transaction=txn)
            if not snapshot.exists:
                return None
            data = snapshot.to_dict() or {}
            record = RunRecord.model_validate(data)

            if record.worker_id != worker_id or record.lease_id != lease_id:
                return None

            updated = record.with_updates(
                heartbeat_at=now,
                lease_expires_at=expires_at,
            )
            txn.set(doc_ref, updated.model_dump(mode="json"))
            return WorkerLease(
                run_id=run_id,
                worker_id=worker_id,
                lease_id=lease_id,
                lease_acquired_at=record.lease_acquired_at or now,
                lease_expires_at=expires_at,
                heartbeat_at=now,
                duration_seconds=duration_seconds,
            )

        lease = await _renew_in_transaction(transaction)
        return lease

    async def release_lease(
        self,
        run_id: str,
        worker_id: str,
        lease_id: str,
    ) -> bool:
        """Release active lease using a Firestore transaction."""
        client = self._get_client()
        doc_ref = client.collection(self._collection_name).document(run_id)

        from google.cloud import firestore

        transaction = client.transaction()

        @firestore.async_transactional
        async def _release_in_transaction(txn: Any) -> bool:
            snapshot = await doc_ref.get(transaction=txn)
            if not snapshot.exists:
                return False
            data = snapshot.to_dict() or {}
            record = RunRecord.model_validate(data)

            if record.worker_id != worker_id or record.lease_id != lease_id:
                return False

            updated = record.with_updates(clear_lease=True)
            txn.set(doc_ref, updated.model_dump(mode="json"))
            return True

        success = await _release_in_transaction(transaction)
        return bool(success)

    async def get_lease(self, run_id: str) -> WorkerLease | None:
        """Fetch current lease state from Firestore."""
        client = self._get_client()
        doc_ref = client.collection(self._collection_name).document(run_id)
        snapshot = await doc_ref.get()
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        record = RunRecord.model_validate(data)

        if (
            record.lease_id is None
            or record.worker_id is None
            or record.lease_expires_at is None
        ):
            return None

        return WorkerLease(
            run_id=record.run_id,
            worker_id=record.worker_id,
            lease_id=record.lease_id,
            lease_acquired_at=record.lease_acquired_at or record.created_at,
            lease_expires_at=record.lease_expires_at,
            heartbeat_at=record.heartbeat_at or record.created_at,
            duration_seconds=max(
                1.0,
                (
                    record.lease_expires_at
                    - (record.lease_acquired_at or record.created_at)
                ).total_seconds(),
            ),
        )


__all__ = [
    "FirestoreLeaseManager",
    "InMemoryLeaseManager",
    "LeaseManagerProtocol",
    "WorkerLease",
    "generate_worker_id",
]
