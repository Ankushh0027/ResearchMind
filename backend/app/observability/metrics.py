"""Dimensional metrics implementations and DAG execution observability bridge hook."""

import logging
import threading
from collections import defaultdict
from typing import Any

from app.observability.models import MetricSummary
from app.observability.protocols import MetricsProtocol, TracerProtocol
from app.orchestration.contracts import TokenUsage
from app.orchestration.protocols import ObservabilityHooksProtocol

logger = logging.getLogger(__name__)


class InMemoryMetricsAccumulator(MetricsProtocol):
    """Thread-safe in-memory metrics accumulator for local execution, testing, and CI."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_runs: int = 0
        self._runs_started: int = 0
        self._runs_completed: int = 0
        self._runs_failed: int = 0
        self._runs_cancelled: int = 0
        self._tasks_started: int = 0
        self._tasks_completed: int = 0
        self._tasks_failed: int = 0
        self._tasks_retried: int = 0
        self._prompt_tokens: int = 0
        self._completion_tokens: int = 0
        self._total_tokens: int = 0
        self._run_durations_ms: list[float] = []
        self._subtask_durations_ms: dict[str, list[float]] = defaultdict(list)
        self._custom_counters: dict[str, int] = defaultdict(int)
        self._custom_gauges: dict[str, float] = {}

    def increment_counter(
        self,
        name: str,
        value: int = 1,
        attributes: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> None:
        with self._lock:
            if name in ("runs_started", "runs.started"):
                self._runs_started += value
            elif name in ("runs_completed", "runs.completed"):
                self._runs_completed += value
            elif name in ("runs_failed", "runs.failed"):
                self._runs_failed += value
            elif name in ("runs_cancelled", "runs.cancelled"):
                self._runs_cancelled += value
            elif name in ("tasks_started", "tasks.started"):
                self._tasks_started += value
            elif name in ("tasks_completed", "tasks.completed"):
                self._tasks_completed += value
            elif name in ("tasks_failed", "tasks.failed"):
                self._tasks_failed += value
            elif name in ("tasks_retried", "tasks.retried"):
                self._tasks_retried += value
            elif name in ("tokens.prompt", "prompt_tokens"):
                self._prompt_tokens += value
            elif name in ("tokens.completion", "completion_tokens"):
                self._completion_tokens += value
            elif name in ("tokens.total", "total_tokens"):
                self._total_tokens += value
            else:
                self._custom_counters[name] += value

    def record_histogram(
        self,
        name: str,
        value: float,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            if name in ("run.duration_ms", "run_duration_ms"):
                self._run_durations_ms.append(value)
            elif name in ("subtask.duration_ms", "subtask_duration_ms"):
                task_id = (
                    str(attributes.get("subtask_id", "default"))
                    if attributes
                    else "default"
                )
                self._subtask_durations_ms[task_id].append(value)

    def set_gauge(
        self,
        name: str,
        value: int | float,
        attributes: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> None:
        with self._lock:
            if name in ("active_runs", "runs.active"):
                self._active_runs = int(value)
            else:
                self._custom_gauges[name] = float(value)

    def get_summary(self) -> MetricSummary:
        with self._lock:
            subtasks_copy = {k: tuple(v) for k, v in self._subtask_durations_ms.items()}
            return MetricSummary(
                active_runs=self._active_runs,
                total_runs_started=self._runs_started,
                total_runs_completed=self._runs_completed,
                total_runs_failed=self._runs_failed,
                total_runs_cancelled=self._runs_cancelled,
                total_tasks_started=self._tasks_started,
                total_tasks_completed=self._tasks_completed,
                total_tasks_failed=self._tasks_failed,
                total_tasks_retried=self._tasks_retried,
                total_prompt_tokens=self._prompt_tokens,
                total_completion_tokens=self._completion_tokens,
                total_tokens=self._total_tokens,
                run_durations_ms=tuple(self._run_durations_ms),
                subtask_durations_ms=subtasks_copy,
            )

    def clear(self) -> None:
        with self._lock:
            self._active_runs = 0
            self._runs_started = 0
            self._runs_completed = 0
            self._runs_failed = 0
            self._runs_cancelled = 0
            self._tasks_started = 0
            self._tasks_completed = 0
            self._tasks_failed = 0
            self._tasks_retried = 0
            self._prompt_tokens = 0
            self._completion_tokens = 0
            self._total_tokens = 0
            self._run_durations_ms.clear()
            self._subtask_durations_ms.clear()
            self._custom_counters.clear()
            self._custom_gauges.clear()


class ObservabilityBridgeHook(ObservabilityHooksProtocol):
    """Bridge connecting DAGExecutor lifecycle events to TracerProtocol and MetricsProtocol."""

    def __init__(
        self,
        tracer: TracerProtocol | None = None,
        metrics: MetricsProtocol | None = None,
    ) -> None:
        self.tracer = tracer
        self.metrics = metrics or InMemoryMetricsAccumulator()

    async def on_run_started(self, run_id: str, plan_id: str) -> None:
        self.metrics.increment_counter(
            "runs_started", attributes={"run_id": run_id, "plan_id": plan_id}
        )
        summary = self.metrics.get_summary()
        self.metrics.set_gauge("active_runs", summary.active_runs + 1)

    async def on_run_completed(
        self, run_id: str, duration_seconds: float, token_usage: TokenUsage
    ) -> None:
        self.metrics.increment_counter("runs_completed", attributes={"run_id": run_id})
        summary = self.metrics.get_summary()
        self.metrics.set_gauge("active_runs", max(0, summary.active_runs - 1))
        self.metrics.record_histogram(
            "run.duration_ms",
            duration_seconds * 1000.0,
            attributes={"run_id": run_id},
        )
        if token_usage.total_tokens > 0:
            self.metrics.increment_counter("tokens.prompt", token_usage.prompt_tokens)
            self.metrics.increment_counter(
                "tokens.completion", token_usage.completion_tokens
            )
            self.metrics.increment_counter("tokens.total", token_usage.total_tokens)

    async def on_task_started(self, run_id: str, subtask_id: str, attempt: int) -> None:
        self.metrics.increment_counter(
            "tasks_started",
            attributes={
                "run_id": run_id,
                "subtask_id": subtask_id,
                "attempt": attempt,
            },
        )

    async def on_task_completed(
        self,
        run_id: str,
        subtask_id: str,
        duration_ms: int,
        token_usage: TokenUsage,
    ) -> None:
        self.metrics.increment_counter(
            "tasks_completed",
            attributes={"run_id": run_id, "subtask_id": subtask_id},
        )
        self.metrics.record_histogram(
            "subtask.duration_ms",
            float(duration_ms),
            attributes={"run_id": run_id, "subtask_id": subtask_id},
        )
        if token_usage.total_tokens > 0:
            self.metrics.increment_counter("tokens.prompt", token_usage.prompt_tokens)
            self.metrics.increment_counter(
                "tokens.completion", token_usage.completion_tokens
            )
            self.metrics.increment_counter("tokens.total", token_usage.total_tokens)

    async def on_task_failed(
        self,
        run_id: str,
        subtask_id: str,
        attempt: int,
        _error: str,
        is_retryable: bool,
    ) -> None:
        self.metrics.increment_counter(
            "tasks_failed",
            attributes={
                "run_id": run_id,
                "subtask_id": subtask_id,
                "attempt": attempt,
                "is_retryable": is_retryable,
            },
        )

    async def on_task_retried(
        self,
        run_id: str,
        subtask_id: str,
        next_attempt: int,
        delay_seconds: float,
    ) -> None:
        self.metrics.increment_counter(
            "tasks_retried",
            attributes={
                "run_id": run_id,
                "subtask_id": subtask_id,
                "next_attempt": next_attempt,
                "delay_seconds": delay_seconds,
            },
        )


__all__ = [
    "InMemoryMetricsAccumulator",
    "ObservabilityBridgeHook",
]
