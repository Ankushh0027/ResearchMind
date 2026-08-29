"""Provider-agnostic interfaces and protocols for distributed tracing and metrics."""

from types import TracebackType
from typing import Any, Protocol, runtime_checkable

from app.observability.models import MetricSummary, SpanContext, SpanStatus


@runtime_checkable
class SpanProtocol(Protocol):
    """Protocol for active or recorded execution trace spans."""

    @property
    def context(self) -> SpanContext:
        """Return the immutable W3C span context."""
        ...

    def set_attribute(self, key: str, value: Any) -> "SpanProtocol":
        """Attach a single sanitized key-value attribute to the span."""
        ...

    def set_attributes(self, attributes: dict[str, Any]) -> "SpanProtocol":
        """Attach multiple key-value attributes to the span."""
        ...

    def record_exception(self, exception: BaseException) -> None:
        """Record an exception event and mark span status as ERROR."""
        ...

    def set_status(self, status: SpanStatus, description: str | None = None) -> None:
        """Explicitly set the span completion status."""
        ...

    def end(self) -> None:
        """Conclude span duration and record final metrics."""
        ...

    def __enter__(self) -> "SpanProtocol": ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...

    async def __aenter__(self) -> "SpanProtocol": ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...


@runtime_checkable
class TracerProtocol(Protocol):
    """Protocol for creating, managing, and propagating distributed trace spans."""

    def start_span(
        self,
        name: str,
        parent: SpanContext | SpanProtocol | str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> SpanProtocol:
        """Create a new unmanaged span."""
        ...

    def start_as_current_span(
        self,
        name: str,
        parent: SpanContext | SpanProtocol | str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Any:
        """Create and activate a span in the current async execution context."""
        ...

    def current_span(self) -> SpanProtocol | None:
        """Return the currently active span in this context, or None."""
        ...

    def current_context(self) -> SpanContext | None:
        """Return the currently active SpanContext, or None."""
        ...

    def inject_context(
        self,
        carrier: dict[str, str],
        context: SpanContext | None = None,
    ) -> None:
        """Inject W3C traceparent headers into a carrier dictionary."""
        ...

    def extract_context(self, carrier: dict[str, str]) -> SpanContext | None:
        """Extract W3C traceparent headers from a carrier dictionary."""
        ...


@runtime_checkable
class MetricsProtocol(Protocol):
    """Protocol for capturing dimensional performance metrics and counters."""

    def increment_counter(
        self,
        name: str,
        value: int = 1,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """Increment a named monotonic counter."""
        ...

    def record_histogram(
        self,
        name: str,
        value: float,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """Record a floating-point duration or distribution sample."""
        ...

    def set_gauge(
        self,
        name: str,
        value: int | float,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """Set the current value of a point-in-time gauge."""
        ...

    def get_summary(self) -> MetricSummary:
        """Return an aggregated snapshot of all recorded metrics."""
        ...


@runtime_checkable
class TelemetryProviderProtocol(Protocol):
    """Protocol combining tracer, metrics, and lifecycle management."""

    @property
    def tracer(self) -> TracerProtocol:
        """Return the configured TracerProtocol."""
        ...

    @property
    def metrics(self) -> MetricsProtocol:
        """Return the configured MetricsProtocol."""
        ...

    def shutdown(self) -> None:
        """Flush and safely conclude any open exporters."""
        ...


__all__ = [
    "MetricsProtocol",
    "SpanProtocol",
    "TelemetryProviderProtocol",
    "TracerProtocol",
]
