"""Distributed tracing implementations: deterministic in-memory tracer and OpenTelemetry adapter."""

import contextlib
import logging
import threading
import time
from datetime import UTC, datetime
from types import TracebackType
from typing import Any

from app.observability.context import (
    get_current_context,
    get_current_span,
    reset_current_context,
    reset_current_span,
    set_current_context,
    set_current_span,
)
from app.observability.logging import SecretScrubber
from app.observability.models import (
    SpanContext,
    SpanRecord,
    SpanStatus,
    generate_span_id,
    generate_trace_id,
)
from app.observability.protocols import SpanProtocol, TracerProtocol

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class InMemorySpan(SpanProtocol):
    """Deterministic, thread-safe in-memory span implementing SpanProtocol."""

    def __init__(
        self,
        name: str,
        context: SpanContext,
        tracer: "InMemoryTracer",
        parent_span_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self._context = context
        self._tracer = tracer
        self.parent_span_id = parent_span_id
        self.start_time = _utc_now()
        self._start_perf = time.perf_counter()
        self.end_time: datetime | None = None
        self.duration_ms: float = 0.0
        self.status = SpanStatus.OK
        self.attributes: dict[str, Any] = (
            SecretScrubber.scrub_data(attributes) if attributes else {}
        )
        self.events: list[dict[str, Any]] = []
        self.error_message: str | None = None
        self._ended = False
        self._token_span: Any = None
        self._token_ctx: Any = None

    @property
    def context(self) -> SpanContext:
        return self._context

    def set_attribute(self, key: str, value: Any) -> "InMemorySpan":
        self.attributes[key] = SecretScrubber.scrub_data(value)
        return self

    def set_attributes(self, attributes: dict[str, Any]) -> "InMemorySpan":
        for k, v in attributes.items():
            self.set_attribute(k, v)
        return self

    def record_exception(self, exception: BaseException) -> None:
        self.status = SpanStatus.ERROR
        self.error_message = SecretScrubber.scrub_text(str(exception))
        self.events.append(
            {
                "timestamp": _utc_now().isoformat(),
                "name": "exception",
                "exception.type": type(exception).__name__,
                "exception.message": self.error_message,
            }
        )

    def set_status(self, status: SpanStatus, description: str | None = None) -> None:
        self.status = status
        if description is not None:
            self.error_message = SecretScrubber.scrub_text(description)

    def end(self) -> None:
        if self._ended:
            return
        self._ended = True
        self.end_time = _utc_now()
        self.duration_ms = (time.perf_counter() - self._start_perf) * 1000.0
        record = SpanRecord(
            name=self.name,
            context=self._context,
            parent_span_id=self.parent_span_id,
            start_time=self.start_time,
            end_time=self.end_time,
            duration_ms=self.duration_ms,
            status=self.status,
            attributes=dict(self.attributes),
            events=tuple(self.events),
            error_message=self.error_message,
        )
        self._tracer._record_span(record)

    def __enter__(self) -> "InMemorySpan":
        self._token_span = set_current_span(self)
        self._token_ctx = set_current_context(self._context)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        try:
            if exc_val is not None:
                self.record_exception(exc_val)
        finally:
            if self._token_ctx is not None:
                reset_current_context(self._token_ctx)
            if self._token_span is not None:
                reset_current_span(self._token_span)
            self.end()

    async def __aenter__(self) -> "InMemorySpan":
        return self.__enter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.__exit__(exc_type, exc_val, exc_tb)


class InMemoryTracer(TracerProtocol):
    """Deterministic, thread-safe in-memory tracer for local execution, testing, and CI."""

    def __init__(self) -> None:
        self._spans: list[SpanRecord] = []
        self._lock = threading.Lock()

    def _record_span(self, span: SpanRecord) -> None:
        with self._lock:
            self._spans.append(span)

    def get_spans(self) -> list[SpanRecord]:
        """Return a snapshot of all completed span records."""
        with self._lock:
            return list(self._spans)

    def clear(self) -> None:
        """Clear recorded spans."""
        with self._lock:
            self._spans.clear()

    def start_span(
        self,
        name: str,
        parent: SpanContext | SpanProtocol | str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> InMemorySpan:
        parent_ctx: SpanContext | None = None
        if isinstance(parent, str):
            parent_ctx = SpanContext.from_traceparent(parent)
        elif isinstance(parent, SpanContext):
            parent_ctx = parent
        elif isinstance(parent, SpanProtocol):
            parent_ctx = parent.context
        elif parent is None:
            parent_ctx = get_current_context()

        if parent_ctx is not None:
            context = SpanContext(
                trace_id=parent_ctx.trace_id,
                span_id=generate_span_id(),
                trace_flags=parent_ctx.trace_flags,
                trace_state=parent_ctx.trace_state,
            )
            parent_span_id = parent_ctx.span_id
        else:
            context = SpanContext(
                trace_id=generate_trace_id(),
                span_id=generate_span_id(),
                trace_flags="01",
            )
            parent_span_id = None

        return InMemorySpan(
            name=name,
            context=context,
            tracer=self,
            parent_span_id=parent_span_id,
            attributes=attributes,
        )

    def start_as_current_span(
        self,
        name: str,
        parent: SpanContext | SpanProtocol | str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> InMemorySpan:
        return self.start_span(name, parent=parent, attributes=attributes)

    def current_span(self) -> SpanProtocol | None:
        return get_current_span()

    def current_context(self) -> SpanContext | None:
        return get_current_context()

    def inject_context(
        self,
        carrier: dict[str, str],
        context: SpanContext | None = None,
    ) -> None:
        ctx = context or get_current_context()
        if ctx is not None:
            carrier["traceparent"] = ctx.to_traceparent()
            if ctx.trace_state:
                carrier["tracestate"] = ctx.trace_state

    def extract_context(self, carrier: dict[str, str]) -> SpanContext | None:
        traceparent: str | None = None
        tracestate = ""
        for k, v in carrier.items():
            lower_k = k.lower()
            if lower_k == "traceparent":
                traceparent = v
            elif lower_k == "tracestate":
                tracestate = v

        if traceparent:
            return SpanContext.from_traceparent(traceparent, trace_state=tracestate)
        return None


class OpenTelemetrySpanAdapter(SpanProtocol):
    """Adapter wrapping an OpenTelemetry Span instance."""

    def __init__(self, otel_span: Any, context: SpanContext) -> None:
        self._otel_span = otel_span
        self._context = context

    @property
    def context(self) -> SpanContext:
        return self._context

    def set_attribute(self, key: str, value: Any) -> "OpenTelemetrySpanAdapter":
        with contextlib.suppress(Exception):
            scrubbed = SecretScrubber.scrub_data(value)
            self._otel_span.set_attribute(key, scrubbed)
        return self

    def set_attributes(self, attributes: dict[str, Any]) -> "OpenTelemetrySpanAdapter":
        for k, v in attributes.items():
            self.set_attribute(k, v)
        return self

    def record_exception(self, exception: BaseException) -> None:
        with contextlib.suppress(Exception):
            self._otel_span.record_exception(exception)

    def set_status(self, status: SpanStatus, description: str | None = None) -> None:
        with contextlib.suppress(Exception):
            from opentelemetry.trace import Status, StatusCode

            otel_status = (
                StatusCode.OK
                if status == SpanStatus.OK
                else StatusCode.ERROR
                if status == SpanStatus.ERROR
                else StatusCode.UNSET
            )
            self._otel_span.set_status(Status(otel_status, description=description))

    def end(self) -> None:
        with contextlib.suppress(Exception):
            self._otel_span.end()

    def __enter__(self) -> "OpenTelemetrySpanAdapter":
        self._otel_span.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self._otel_span.__exit__(exc_type, exc_val, exc_tb)

    async def __aenter__(self) -> "OpenTelemetrySpanAdapter":
        return self.__enter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.__exit__(exc_type, exc_val, exc_tb)


class OpenTelemetryTracer(TracerProtocol):
    """Production OpenTelemetry tracer delegating to standard OpenTelemetry SDK."""

    def __init__(
        self,
        service_name: str = "researchmind",
        otlp_endpoint: str = "http://localhost:4317",
        sampling_ratio: float = 1.0,
    ) -> None:
        self.service_name = service_name
        self.otlp_endpoint = otlp_endpoint
        self.sampling_ratio = sampling_ratio
        self._fallback = InMemoryTracer()
        self._otel_tracer: Any = None
        self._init_otel()

    def _init_otel(self) -> None:
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.resources import SERVICE_NAME, Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.sampling import (
                DEFAULT_OFF,
                DEFAULT_ON,
                TraceIdRatioBased,
            )

            resource = Resource.create({SERVICE_NAME: self.service_name})
            sampler = (
                DEFAULT_ON
                if self.sampling_ratio >= 1.0
                else DEFAULT_OFF
                if self.sampling_ratio <= 0.0
                else TraceIdRatioBased(self.sampling_ratio)
            )
            provider = TracerProvider(resource=resource, sampler=sampler)
            trace.set_tracer_provider(provider)
            self._otel_tracer = trace.get_tracer(self.service_name)
        except Exception as e:
            logger.warning(
                "OpenTelemetry SDK initialization failed (%s); falling back to InMemoryTracer.",
                e,
            )
            self._otel_tracer = None

    def start_span(
        self,
        name: str,
        parent: SpanContext | SpanProtocol | str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> SpanProtocol:
        if self._otel_tracer is None:
            return self._fallback.start_span(name, parent=parent, attributes=attributes)

        try:
            scrubbed_attrs = SecretScrubber.scrub_data(attributes) if attributes else {}
            raw_span = self._otel_tracer.start_span(name, attributes=scrubbed_attrs)
            span_ctx = raw_span.get_span_context()
            context = SpanContext(
                trace_id=f"{span_ctx.trace_id:032x}",
                span_id=f"{span_ctx.span_id:016x}",
                trace_flags=f"{span_ctx.trace_flags:02x}",
            )
            return OpenTelemetrySpanAdapter(raw_span, context)
        except Exception as e:
            logger.warning("Failed creating OpenTelemetry span (%s); falling back.", e)
            return self._fallback.start_span(name, parent=parent, attributes=attributes)

    def start_as_current_span(
        self,
        name: str,
        parent: SpanContext | SpanProtocol | str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Any:
        span = self.start_span(name, parent=parent, attributes=attributes)
        return span

    def current_span(self) -> SpanProtocol | None:
        return get_current_span()

    def current_context(self) -> SpanContext | None:
        return get_current_context()

    def inject_context(
        self,
        carrier: dict[str, str],
        context: SpanContext | None = None,
    ) -> None:
        self._fallback.inject_context(carrier, context=context)

    def extract_context(self, carrier: dict[str, str]) -> SpanContext | None:
        return self._fallback.extract_context(carrier)


__all__ = [
    "InMemorySpan",
    "InMemoryTracer",
    "OpenTelemetrySpanAdapter",
    "OpenTelemetryTracer",
]
