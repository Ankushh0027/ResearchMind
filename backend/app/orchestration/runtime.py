"""Runtime infrastructure adapters including in-memory repositories and telemetry sinks."""

import asyncio
from collections import defaultdict

from app.orchestration.contracts import TokenUsage
from app.orchestration.events import ExecutionEvent
from app.orchestration.protocols import (
    CheckpointRepositoryProtocol,
    EventSinkProtocol,
    ObservabilityHooksProtocol,
)
from app.state.snapshot import CheckpointSnapshot


class InMemoryCheckpointRepository(CheckpointRepositoryProtocol):
    """Thread-safe and async-safe in-memory repository for checkpoint snapshots."""

    def __init__(self) -> None:
        self._snapshots: dict[str, list[CheckpointSnapshot]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def save_checkpoint(self, snapshot: CheckpointSnapshot) -> None:
        """Persist a checkpoint snapshot."""
        snapshot.assert_valid()
        async with self._lock:
            self._snapshots[snapshot.run_id].append(snapshot)

    async def load_latest_checkpoint(self, run_id: str) -> CheckpointSnapshot | None:
        """Retrieve the most recent checkpoint for a run ID."""
        async with self._lock:
            history = self._snapshots.get(run_id, [])
            if not history:
                return None
            return history[-1]

    async def list_checkpoints(self, run_id: str) -> list[CheckpointSnapshot]:
        """List all stored checkpoints for a run ID."""
        async with self._lock:
            return list(self._snapshots.get(run_id, []))


class InMemoryEventSink(EventSinkProtocol):
    """Thread-safe in-memory execution event sink for testing and stream buffering."""

    def __init__(self) -> None:
        self._events: list[ExecutionEvent] = []
        self._lock = asyncio.Lock()

    async def emit(self, event: object) -> None:
        """Capture an emitted execution event."""
        if isinstance(event, ExecutionEvent):
            async with self._lock:
                self._events.append(event)

    def get_events(self, run_id: str | None = None) -> list[ExecutionEvent]:
        """Retrieve recorded events, optionally filtered by run_id."""
        if run_id is None:
            return list(self._events)
        return [e for e in self._events if e.run_id == run_id]

    def clear(self) -> None:
        """Clear all stored events."""
        self._events.clear()


class MetricsCollector(ObservabilityHooksProtocol):
    """Observability collector tracking execution metrics, latencies, and token consumption."""

    def __init__(self) -> None:
        self.runs_started: int = 0
        self.runs_completed: int = 0
        self.tasks_started: int = 0
        self.tasks_completed: int = 0
        self.tasks_failed: int = 0
        self.tasks_retried: int = 0
        self.total_task_duration_ms: int = 0
        self.total_token_usage: TokenUsage = TokenUsage()
        self.task_durations: dict[str, list[int]] = defaultdict(list)

    async def on_run_started(self, _run_id: str, _plan_id: str) -> None:
        self.runs_started += 1

    async def on_run_completed(
        self, _run_id: str, _duration_seconds: float, _token_usage: TokenUsage
    ) -> None:
        self.runs_completed += 1

    async def on_task_started(
        self, _run_id: str, _subtask_id: str, _attempt: int
    ) -> None:
        self.tasks_started += 1

    async def on_task_completed(
        self,
        _run_id: str,
        subtask_id: str,
        duration_ms: int,
        token_usage: TokenUsage,
    ) -> None:
        self.tasks_completed += 1
        self.total_task_duration_ms += duration_ms
        self.task_durations[subtask_id].append(duration_ms)
        self.total_token_usage = TokenUsage(
            prompt_tokens=self.total_token_usage.prompt_tokens
            + token_usage.prompt_tokens,
            completion_tokens=self.total_token_usage.completion_tokens
            + token_usage.completion_tokens,
            total_tokens=self.total_token_usage.total_tokens + token_usage.total_tokens,
        )

    async def on_task_failed(
        self,
        _run_id: str,
        _subtask_id: str,
        _attempt: int,
        _error: str,
        _is_retryable: bool,
    ) -> None:
        self.tasks_failed += 1

    async def on_task_retried(
        self,
        _run_id: str,
        _subtask_id: str,
        _next_attempt: int,
        _delay_seconds: float,
    ) -> None:
        self.tasks_retried += 1
