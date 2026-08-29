"""Domain models and schemas for distributed tracing, metrics, and observability."""

import re
import secrets
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_TRACEPARENT_REGEX = re.compile(
    r"^00-([0-9a-fA-F]{32})-([0-9a-fA-F]{16})-([0-9a-fA-F]{2})$"
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def generate_trace_id() -> str:
    """Generate a 32-character hexadecimal W3C trace identifier."""
    return secrets.token_hex(16)


def generate_span_id() -> str:
    """Generate a 16-character hexadecimal W3C span identifier."""
    return secrets.token_hex(8)


class SpanStatus(StrEnum):
    """Execution status for a trace span."""

    UNSET = "UNSET"
    OK = "OK"
    ERROR = "ERROR"


class SpanContext(BaseModel):
    """Immutable representation of a W3C distributed trace context."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_id: str = Field(
        default_factory=generate_trace_id,
        min_length=32,
        max_length=32,
        description="32-character hex trace identifier",
    )
    span_id: str = Field(
        default_factory=generate_span_id,
        min_length=16,
        max_length=16,
        description="16-character hex span identifier",
    )
    trace_flags: str = Field(
        default="01",
        min_length=2,
        max_length=2,
        description="2-character hex trace flags (01 = sampled)",
    )
    trace_state: str = Field(
        default="",
        description="Optional W3C vendor-specific trace state",
    )

    @property
    def is_sampled(self) -> bool:
        """Return True if the sampled flag bit is active."""
        try:
            return (int(self.trace_flags, 16) & 0x01) == 1
        except ValueError:
            return False

    def to_traceparent(self) -> str:
        """Format as a W3C traceparent header string."""
        return f"00-{self.trace_id}-{self.span_id}-{self.trace_flags}"

    @classmethod
    def from_traceparent(
        cls, traceparent: str, trace_state: str = ""
    ) -> "SpanContext | None":
        """Parse a W3C traceparent header string into a SpanContext, or return None if malformed."""
        if not traceparent or not isinstance(traceparent, str):
            return None
        match = _TRACEPARENT_REGEX.match(traceparent.strip())
        if not match:
            return None
        trace_id, span_id, trace_flags = match.groups()
        # Verify trace_id and span_id are not all zeros
        if trace_id == "0" * 32 or span_id == "0" * 16:
            return None
        return cls(
            trace_id=trace_id.lower(),
            span_id=span_id.lower(),
            trace_flags=trace_flags.lower(),
            trace_state=trace_state.strip(),
        )


class SpanRecord(BaseModel):
    """Immutable record representing a completed trace span for testing and auditing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(..., description="Human-readable span operation name")
    context: SpanContext = Field(..., description="Span W3C context")
    parent_span_id: str | None = Field(
        default=None, description="Parent span identifier if nested"
    )
    start_time: datetime = Field(
        default_factory=_utc_now, description="Span start timestamp"
    )
    end_time: datetime | None = Field(default=None, description="Span finish timestamp")
    duration_ms: float = Field(
        default=0.0, ge=0.0, description="Duration of the span in milliseconds"
    )
    status: SpanStatus = Field(
        default=SpanStatus.OK, description="Span completion status"
    )
    attributes: dict[str, Any] = Field(
        default_factory=dict, description="Sanitized key-value span attributes"
    )
    events: tuple[dict[str, Any], ...] = Field(
        default_factory=tuple, description="Inline events attached to the span"
    )
    error_message: str | None = Field(
        default=None, description="Error description if status is ERROR"
    )


class MetricSummary(BaseModel):
    """Aggregated snapshot of system metrics and performance counters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    active_runs: int = Field(default=0, ge=0, description="Current in-flight runs")
    total_runs_started: int = Field(default=0, ge=0, description="Total runs initiated")
    total_runs_completed: int = Field(
        default=0, ge=0, description="Total runs completed"
    )
    total_runs_failed: int = Field(default=0, ge=0, description="Total runs failed")
    total_runs_cancelled: int = Field(
        default=0, ge=0, description="Total runs cancelled"
    )
    total_tasks_started: int = Field(
        default=0, ge=0, description="Total subtasks executed"
    )
    total_tasks_completed: int = Field(
        default=0, ge=0, description="Total subtasks succeeded"
    )
    total_tasks_failed: int = Field(
        default=0, ge=0, description="Total subtasks failed"
    )
    total_tasks_retried: int = Field(
        default=0, ge=0, description="Total retry attempts"
    )
    total_prompt_tokens: int = Field(
        default=0, ge=0, description="Total LLM prompt tokens consumed"
    )
    total_completion_tokens: int = Field(
        default=0, ge=0, description="Total LLM completion tokens generated"
    )
    total_tokens: int = Field(
        default=0, ge=0, description="Total aggregated token usage"
    )
    run_durations_ms: tuple[float, ...] = Field(
        default_factory=tuple, description="Recorded research run durations"
    )
    subtask_durations_ms: dict[str, tuple[float, ...]] = Field(
        default_factory=dict, description="Recorded subtask durations by task ID"
    )


__all__ = [
    "MetricSummary",
    "SpanContext",
    "SpanRecord",
    "SpanStatus",
    "generate_span_id",
    "generate_trace_id",
]
