from typing import Any

import pytest

from app.common.enums import RunStage
from app.persistence.firestore import (
    FirestoreCheckpointRepository,
    FirestoreRunRepository,
)
from app.persistence.protocols import RunRecord
from app.state.models import ResearchGoal
from app.state.snapshot import CheckpointSnapshot, compute_state_hash


class FakeDocumentSnapshot:
    """Fake Firestore DocumentSnapshot for deterministic unit testing."""

    def __init__(
        self, doc_id: str, data: dict[str, Any] | None, exists: bool = True
    ) -> None:
        self.id = doc_id
        self._data = data
        self.exists = exists

    def to_dict(self) -> dict[str, Any] | None:
        return self._data


class FakeDocumentReference:
    """Fake Firestore DocumentReference."""

    def __init__(self, doc_id: str, collection_dict: dict[str, dict[str, Any]]) -> None:
        self.id = doc_id
        self._collection_dict = collection_dict

    async def get(self) -> FakeDocumentSnapshot:
        if self.id in self._collection_dict:
            return FakeDocumentSnapshot(
                self.id, self._collection_dict[self.id], exists=True
            )
        return FakeDocumentSnapshot(self.id, None, exists=False)

    async def set(self, data: dict[str, Any]) -> None:
        self._collection_dict[self.id] = dict(data)


class FakeQuery:
    """Fake Firestore Query supporting where, order_by, limit, and offset."""

    def __init__(self, collection_dict: dict[str, dict[str, Any]]) -> None:
        self._collection_dict = collection_dict
        self._filters: list[tuple[str, str, object]] = []
        self._order_by: tuple[str, str] | None = None
        self._limit: int | None = None
        self._offset: int = 0

    def where(self, field: str, op: str, value: object) -> "FakeQuery":
        self._filters.append((field, op, value))
        return self

    def order_by(self, field: str, direction: str = "ASCENDING") -> "FakeQuery":
        self._order_by = (field, direction)
        return self

    def offset(self, num: int) -> "FakeQuery":
        self._offset = num
        return self

    def limit(self, num: int) -> "FakeQuery":
        self._limit = num
        return self

    async def get(self) -> list[FakeDocumentSnapshot]:
        docs = [
            FakeDocumentSnapshot(doc_id, data, exists=True)
            for doc_id, data in self._collection_dict.items()
        ]
        # Apply filters
        for field, op, value in self._filters:
            if op == "==":
                docs = [
                    d
                    for d in docs
                    if d.to_dict() is not None and d.to_dict().get(field) == value  # type: ignore[union-attr]
                ]

        # Apply ordering
        if self._order_by:
            field, direction = self._order_by
            reverse = direction.upper() == "DESCENDING"
            docs.sort(key=lambda d: (d.to_dict() or {}).get(field, 0), reverse=reverse)

        # Apply offset and limit
        sliced = docs[self._offset :]
        if self._limit is not None:
            sliced = sliced[: self._limit]
        return sliced


class FakeCollectionReference:
    """Fake Firestore CollectionReference."""

    def __init__(self) -> None:
        self._docs: dict[str, dict[str, Any]] = {}

    def document(self, doc_id: str) -> FakeDocumentReference:
        return FakeDocumentReference(doc_id, self._docs)

    def order_by(self, field: str, direction: str = "ASCENDING") -> FakeQuery:
        query = FakeQuery(self._docs)
        return query.order_by(field, direction)

    def where(self, field: str, op: str, value: object) -> FakeQuery:
        query = FakeQuery(self._docs)
        return query.where(field, op, value)


class FakeFirestoreClient:
    """Fake top-level Firestore client."""

    def __init__(self) -> None:
        self._collections: dict[str, FakeCollectionReference] = {}

    def collection(self, name: str) -> FakeCollectionReference:
        if name not in self._collections:
            self._collections[name] = FakeCollectionReference()
        return self._collections[name]


@pytest.fixture
def fake_client() -> FakeFirestoreClient:
    return FakeFirestoreClient()


@pytest.fixture
def firestore_run_repo(fake_client: FakeFirestoreClient) -> FirestoreRunRepository:
    return FirestoreRunRepository(client=fake_client, collection_name="test_runs")


@pytest.fixture
def firestore_checkpoint_repo(
    fake_client: FakeFirestoreClient,
) -> FirestoreCheckpointRepository:
    return FirestoreCheckpointRepository(
        client=fake_client, collection_name="test_checkpoints"
    )


@pytest.mark.asyncio
async def test_firestore_run_repo_crud(
    firestore_run_repo: FirestoreRunRepository,
) -> None:
    """Test 1: Verify FirestoreRunRepository create, get, list, and duplicate check."""
    goal = ResearchGoal(
        goal_id="goal_fs_01",
        query="Verify superconducting qubits coherence times",
    )
    record = RunRecord(run_id="run_fs_01", goal=goal)

    # Create run
    created = await firestore_run_repo.create_run(record)
    assert created.run_id == "run_fs_01"

    # Reject duplicate
    with pytest.raises(ValueError, match="already exists in Firestore"):
        await firestore_run_repo.create_run(record)

    # Get run
    fetched = await firestore_run_repo.get_run("run_fs_01")
    assert fetched is not None
    assert fetched.run_id == "run_fs_01"
    assert fetched.goal.query == goal.query

    # Missing run
    assert await firestore_run_repo.get_run("nonexistent") is None


@pytest.mark.asyncio
async def test_firestore_run_repo_optimistic_locking(
    firestore_run_repo: FirestoreRunRepository,
) -> None:
    """Test 2: Verify Firestore optimistic locking on update."""
    goal = ResearchGoal(goal_id="goal_fs_02", query="LLM reasoning benchmark")
    record = RunRecord(run_id="run_fs_02", goal=goal, version=1)

    await firestore_run_repo.create_run(record)

    # Valid update
    updated = record.with_updates(status=RunStage.PLANNING)
    await firestore_run_repo.update_run(updated, expected_version=1)

    fetched = await firestore_run_repo.get_run("run_fs_02")
    assert fetched is not None
    assert fetched.version == 2
    assert fetched.status == RunStage.PLANNING

    # Stale version update conflict
    stale_update = record.with_updates(status=RunStage.FAILED)
    with pytest.raises(ValueError, match="Optimistic lock conflict"):
        await firestore_run_repo.update_run(stale_update, expected_version=1)


@pytest.mark.asyncio
async def test_firestore_checkpoint_repo_save_and_load(
    firestore_checkpoint_repo: FirestoreCheckpointRepository,
) -> None:
    """Test 3: Verify FirestoreCheckpointRepository save and load_latest with hash integrity."""
    payload = {"state_var": "val1", "counter": 42}
    valid_hash = compute_state_hash(payload)

    snap1 = CheckpointSnapshot(
        snapshot_id="snap_fs_01",
        run_id="run_chk_01",
        stage=RunStage.RESEARCHING,
        checkpoint_version=1,
        state_hash=valid_hash,
        state_payload=payload,
    )
    snap2 = CheckpointSnapshot(
        snapshot_id="snap_fs_02",
        run_id="run_chk_01",
        stage=RunStage.ANALYZING,
        checkpoint_version=2,
        state_hash=valid_hash,
        state_payload=payload,
    )

    await firestore_checkpoint_repo.save_checkpoint(snap1)
    await firestore_checkpoint_repo.save_checkpoint(snap2)

    latest = await firestore_checkpoint_repo.load_latest_checkpoint("run_chk_01")
    assert latest is not None
    assert latest.snapshot_id == "snap_fs_02"
    assert latest.checkpoint_version == 2
    assert latest.stage == RunStage.ANALYZING

    all_snaps = await firestore_checkpoint_repo.list_checkpoints("run_chk_01")
    assert len(all_snaps) == 2
    assert all_snaps[0].checkpoint_version == 1
    assert all_snaps[1].checkpoint_version == 2


def test_firestore_missing_dependency_error() -> None:
    """Test 4: Verify clear runtime error if google-cloud-firestore is uninstalled and no client is injected."""
    repo = FirestoreRunRepository()
    with pytest.raises(RuntimeError, match="google-cloud-firestore is required"):
        repo._get_client()
