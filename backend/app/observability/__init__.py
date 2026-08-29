"""Observability and distributed tracing package for ResearchMind."""

from app.observability.context import (
    get_current_context,
    get_current_span,
    reset_current_context,
    reset_current_span,
    set_current_context,
    set_current_span,
)
from app.observability.factory import (
    DefaultTelemetryProvider,
    create_telemetry_provider,
    get_global_telemetry_provider,
    get_metrics,
    get_tracer,
    set_global_telemetry_provider,
)
from app.observability.logging import (
    SecretScrubber,
    StructuredJsonLogFormatter,
)
from app.observability.metrics import (
    InMemoryMetricsAccumulator,
    ObservabilityBridgeHook,
)
from app.observability.middleware import TraceContextMiddleware
from app.observability.models import (
    MetricSummary,
    SpanContext,
    SpanRecord,
    SpanStatus,
    generate_span_id,
    generate_trace_id,
)
from app.observability.protocols import (
    MetricsProtocol,
    SpanProtocol,
    TelemetryProviderProtocol,
    TracerProtocol,
)
from app.observability.tracing import (
    InMemorySpan,
    InMemoryTracer,
    OpenTelemetrySpanAdapter,
    OpenTelemetryTracer,
)

__all__ = [
    "DefaultTelemetryProvider",
    "InMemoryMetricsAccumulator",
    "InMemorySpan",
    "InMemoryTracer",
    "MetricSummary",
    "MetricsProtocol",
    "ObservabilityBridgeHook",
    "OpenTelemetrySpanAdapter",
    "OpenTelemetryTracer",
    "SecretScrubber",
    "SpanContext",
    "SpanProtocol",
    "SpanRecord",
    "SpanStatus",
    "StructuredJsonLogFormatter",
    "TelemetryProviderProtocol",
    "TraceContextMiddleware",
    "TracerProtocol",
    "create_telemetry_provider",
    "generate_span_id",
    "generate_trace_id",
    "get_current_context",
    "get_current_span",
    "get_global_telemetry_provider",
    "get_metrics",
    "get_tracer",
    "reset_current_context",
    "reset_current_span",
    "set_current_context",
    "set_current_span",
    "set_global_telemetry_provider",
]
