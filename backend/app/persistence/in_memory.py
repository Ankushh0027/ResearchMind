"""In-memory reference implementations of persistence protocols for testing and local execution."""

import asyncio
from collections import defaultdict

from app.orchestration.events import ExecutionEvent
from app.orchestration.runtime import InMemoryCheckpointRepository
from app.persistence.protocols import (
    EventRepositoryProtocol,
    RunRecord,
    RunRepositoryProtocol,
)


class InMemoryRunRepository(RunRepositoryProtocol):
    """Thread-safe and async-safe in-memory repository for research run records."""

    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._lock = asyncio.Lock()

    async def create_run(self, record: RunRecord) -> RunRecord:
        """Persist a new research run record. Fails if run_id already exists."""
        async with self._lock:
            if record.run_id in self._runs:
                raise ValueError(
                    f"RunRecord with run_id '{record.run_id}' already exists"
                )
            self._runs[record.run_id] = record
            return record

    async def get_run(self, run_id: str) -> RunRecord | None:
        """Retrieve a run record by run_id."""
        async with self._lock:
            return self._runs.get(run_id)

    async def update_run(
        self, record: RunRecord, expected_version: int | None = None
    ) -> RunRecord:
        """Update an existing run record with optimistic version validation."""
        async with self._lock:
            existing = self._runs.get(record.run_id)
            if existing is None:
                raise KeyError(f"RunRecord with run_id '{record.run_id}' not found")
            if expected_version is not None and existing.version != expected_version:
                raise ValueError(
                    f"Optimistic lock conflict for run '{record.run_id}': "
                    f"expected version {expected_version}, but found {existing.version}"
                )
            self._runs[record.run_id] = record
            return record

    async def list_runs(self, limit: int = 50, offset: int = 0) -> list[RunRecord]:
        """List stored runs ordered by creation timestamp descending."""
        async with self._lock:
            all_runs = sorted(
                self._runs.values(), key=lambda r: r.created_at, reverse=True
            )
            return all_runs[offset : offset + limit]


class InMemoryEventRepository(EventRepositoryProtocol):
    """Thread-safe in-memory event repository for event replay and persistence."""

    def __init__(self) -> None:
        self._events_by_run: dict[str, list[ExecutionEvent]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def emit_event(self, event: ExecutionEvent) -> None:
        """Persist an execution event."""
        async with self._lock:
            self._events_by_run[event.run_id].append(event)

    async def get_events(
        self, run_id: str, after_index: int = 0
    ) -> list[ExecutionEvent]:
        """Retrieve chronological execution events for a run."""
        async with self._lock:
            events = self._events_by_run.get(run_id, [])
            if after_index >= len(events):
                return []
            return list(events[after_index:])


__all__ = [
    "InMemoryCheckpointRepository",
    "InMemoryEventRepository",
    "InMemoryRunRepository",
]
