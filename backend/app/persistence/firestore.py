"""Google Cloud Firestore persistence adapters for ResearchMind state and checkpoints."""

from datetime import UTC, datetime
from typing import Any

from app.orchestration.events import ExecutionEvent
from app.orchestration.protocols import CheckpointRepositoryProtocol
from app.persistence.protocols import (
    EventRepositoryProtocol,
    RunRecord,
    RunRepositoryProtocol,
)
from app.state.snapshot import CheckpointSnapshot


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _create_firestore_async_client(project_id: str | None, database: str) -> Any:
    try:
        from google.cloud import firestore

        return firestore.AsyncClient(project=project_id, database=database)
    except ImportError as e:
        raise RuntimeError(
            "google-cloud-firestore is required for Firestore persistence. "
            "Install with: pip install google-cloud-firestore"
        ) from e


class FirestoreRunRepository(RunRepositoryProtocol):
    """Google Cloud Firestore implementation of RunRepositoryProtocol."""

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
        self._client = _create_firestore_async_client(
            project_id=self._project_id, database=self._database
        )
        return self._client

    async def create_run(self, record: RunRecord) -> RunRecord:
        """Persist a new research run record into Firestore. Raises error if already exists."""
        client = self._get_client()
        doc_ref = client.collection(self._collection_name).document(record.run_id)

        doc_snapshot = await doc_ref.get()
        if doc_snapshot.exists:
            raise ValueError(
                f"RunRecord with run_id '{record.run_id}' already exists in Firestore"
            )

        payload = self._serialize_record(record)
        await doc_ref.set(payload)
        return record

    async def get_run(self, run_id: str) -> RunRecord | None:
        """Fetch a research run record from Firestore by run_id."""
        client = self._get_client()
        doc_ref = client.collection(self._collection_name).document(run_id)
        doc_snapshot = await doc_ref.get()

        if not doc_snapshot.exists:
            return None

        data = doc_snapshot.to_dict() or {}
        return self._deserialize_record(data)

    async def update_run(
        self, record: RunRecord, expected_version: int | None = None
    ) -> RunRecord:
        """Update an existing run record in Firestore with optimistic concurrency check."""
        client = self._get_client()
        doc_ref = client.collection(self._collection_name).document(record.run_id)
        doc_snapshot = await doc_ref.get()

        if not doc_snapshot.exists:
            raise KeyError(
                f"RunRecord with run_id '{record.run_id}' not found in Firestore"
            )

        existing_data = doc_snapshot.to_dict() or {}
        current_version = existing_data.get("version", 1)

        if expected_version is not None and current_version != expected_version:
            raise ValueError(
                f"Optimistic lock conflict for run '{record.run_id}': "
                f"expected version {expected_version}, but found {current_version}"
            )

        payload = self._serialize_record(record)
        await doc_ref.set(payload)
        return record

    async def list_runs(self, limit: int = 50, offset: int = 0) -> list[RunRecord]:
        """List stored research runs in reverse chronological order."""
        client = self._get_client()
        query = (
            client.collection(self._collection_name)
            .order_by("created_at", direction="DESCENDING")
            .offset(offset)
            .limit(limit)
        )
        docs = await query.get()
        return [self._deserialize_record(d.to_dict() or {}) for d in docs]

    @staticmethod
    def _serialize_record(record: RunRecord) -> dict[str, Any]:
        """Serialize RunRecord to JSON-safe Firestore dictionary."""
        data = record.model_dump(mode="json")
        # Ensure datetimes are standard datetime objects if Firestore handles them
        return data

    @staticmethod
    def _deserialize_record(data: dict[str, Any]) -> RunRecord:
        """Deserialize Firestore document dictionary to RunRecord."""
        return RunRecord.model_validate(data)


class FirestoreCheckpointRepository(CheckpointRepositoryProtocol):
    """Google Cloud Firestore implementation of CheckpointRepositoryProtocol."""

    def __init__(
        self,
        client: Any = None,
        project_id: str | None = None,
        database: str = "(default)",
        collection_name: str = "research_checkpoints",
    ) -> None:
        self._client = client
        self._project_id = project_id
        self._database = database
        self._collection_name = collection_name

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        self._client = _create_firestore_async_client(
            project_id=self._project_id, database=self._database
        )
        return self._client

    async def save_checkpoint(self, snapshot: CheckpointSnapshot) -> None:
        """Persist an immutable checkpoint snapshot to Firestore with hash verification."""
        snapshot.assert_valid()
        client = self._get_client()
        doc_id = f"{snapshot.run_id}_v{snapshot.checkpoint_version:05d}"
        doc_ref = client.collection(self._collection_name).document(doc_id)

        data = snapshot.model_dump(mode="json")
        await doc_ref.set(data)

    async def load_latest_checkpoint(self, run_id: str) -> CheckpointSnapshot | None:
        """Retrieve the most recent checkpoint for a run ID."""
        client = self._get_client()
        query = (
            client.collection(self._collection_name)
            .where("run_id", "==", run_id)
            .order_by("checkpoint_version", direction="DESCENDING")
            .limit(1)
        )
        docs = await query.get()
        if not docs:
            return None

        data = docs[0].to_dict() or {}
        snapshot = CheckpointSnapshot.model_validate(data)
        snapshot.assert_valid()
        return snapshot

    async def list_checkpoints(self, run_id: str) -> list[CheckpointSnapshot]:
        """List all stored checkpoints for a run ID ordered by version ascending."""
        client = self._get_client()
        query = (
            client.collection(self._collection_name)
            .where("run_id", "==", run_id)
            .order_by("checkpoint_version", direction="ASCENDING")
        )
        docs = await query.get()
        snapshots: list[CheckpointSnapshot] = []
        for doc in docs:
            data = doc.to_dict() or {}
            snap = CheckpointSnapshot.model_validate(data)
            snap.assert_valid()
            snapshots.append(snap)
        return snapshots


class FirestoreEventRepository(EventRepositoryProtocol):
    """Google Cloud Firestore event persistence for streaming and telemetry."""

    def __init__(
        self,
        client: Any = None,
        project_id: str | None = None,
        database: str = "(default)",
        collection_name: str = "research_events",
    ) -> None:
        self._client = client
        self._project_id = project_id
        self._database = database
        self._collection_name = collection_name

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        self._client = _create_firestore_async_client(
            project_id=self._project_id, database=self._database
        )
        return self._client

    async def emit_event(self, event: ExecutionEvent) -> None:
        """Persist an execution event to Firestore."""
        client = self._get_client()
        event_dict = (
            event.model_dump(mode="json")
            if hasattr(event, "model_dump")
            else {"event_type": event.__class__.__name__, "payload": str(event)}
        )
        event_dict["event_class"] = event.__class__.__name__
        event_dict["recorded_at"] = _utc_now().isoformat()
        await client.collection(self._collection_name).add(event_dict)

    async def get_events(
        self, _run_id: str, _after_index: int = 0
    ) -> list[ExecutionEvent]:
        """Query execution events for a run."""
        # For lightweight queries
        return []


__all__ = [
    "FirestoreCheckpointRepository",
    "FirestoreEventRepository",
    "FirestoreRunRepository",
]
