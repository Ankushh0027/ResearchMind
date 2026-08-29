"""Unit tests for Phase 6.7: Distributed OpenTelemetry Tracing, Structured Metrics & Observability."""

import json
import logging
from typing import Any

import pytest

from app.config.settings import AppSettings
from app.observability import (
    DefaultTelemetryProvider,
    InMemoryMetricsAccumulator,
    InMemoryTracer,
    MetricsProtocol,
    MetricSummary,
    ObservabilityBridgeHook,
    SecretScrubber,
    SpanContext,
    SpanProtocol,
    SpanStatus,
    StructuredJsonLogFormatter,
    TelemetryProviderProtocol,
    TracerProtocol,
    create_telemetry_provider,
    get_current_context,
    get_current_span,
    get_metrics,
    get_tracer,
)
from app.orchestration.contracts import TokenUsage
from app.orchestration.protocols import ObservabilityHooksProtocol

# =====================================================================
# 1. Protocol Conformance Tests
# =====================================================================


def test_protocol_conformance() -> None:
    """Verify that all observability components satisfy their respective Protocol contracts."""
    tracer = InMemoryTracer()
    span = tracer.start_span("test_span")
    metrics = InMemoryMetricsAccumulator()
    provider = DefaultTelemetryProvider(tracer=tracer, metrics=metrics)
    hook = ObservabilityBridgeHook(tracer=tracer, metrics=metrics)

    assert isinstance(tracer, TracerProtocol)
    assert isinstance(span, SpanProtocol)
    assert isinstance(metrics, MetricsProtocol)
    assert isinstance(provider, TelemetryProviderProtocol)
    assert isinstance(hook, ObservabilityHooksProtocol)


# =====================================================================
# 2. SpanContext and W3C Traceparent Tests
# =====================================================================


def test_span_context_generation() -> None:
    """Verify default generation of 32-char trace_id and 16-char span_id."""
    ctx = SpanContext()
    assert len(ctx.trace_id) == 32
    assert len(ctx.span_id) == 16
    assert ctx.trace_flags == "01"
    assert ctx.is_sampled is True

    traceparent = ctx.to_traceparent()
    assert traceparent == f"00-{ctx.trace_id}-{ctx.span_id}-01"


def test_span_context_from_valid_traceparent() -> None:
    """Verify parsing valid W3C traceparent header string."""
    valid_tp = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    ctx = SpanContext.from_traceparent(valid_tp, trace_state="rojo=1")
    assert ctx is not None
    assert ctx.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert ctx.span_id == "00f067aa0ba902b7"
    assert ctx.trace_flags == "01"
    assert ctx.trace_state == "rojo=1"
    assert ctx.is_sampled is True


@pytest.mark.parametrize(
    "invalid_tp",
    [
        "",
        "invalid",
        "01-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",  # bad version
        "00-00000000000000000000000000000000-00f067aa0ba902b7-01",  # all zero trace_id
        "00-4bf92f3577b34da6a3ce929d0e0e4736-0000000000000000-01",  # all zero span_id
        "00-4bf92f3577b34da6a3ce929d0e0e473-00f067aa0ba902b7-01",  # short trace_id
        "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b-01",  # short span_id
        "00-4bf92f3577b34da6a3ce929d0e0e473g-00f067aa0ba902b7-01",  # non-hex
    ],
)
def test_span_context_from_invalid_traceparent(invalid_tp: str) -> None:
    """Verify malformed traceparent headers safely return None."""
    ctx = SpanContext.from_traceparent(invalid_tp)
    assert ctx is None


# =====================================================================
# 3. InMemoryTracer and Span Lifecycle Tests
# =====================================================================


def test_in_memory_span_lifecycle() -> None:
    """Verify basic span creation, attribute assignment, status, and duration calculation."""
    tracer = InMemoryTracer()
    span = tracer.start_span("operation_a", attributes={"service.name": "test"})
    assert span.name == "operation_a"
    assert span.attributes["service.name"] == "test"
    assert span.status == SpanStatus.OK

    span.set_attribute("http.status", 200)
    span.set_attributes({"user.id": "usr_123", "retry.count": 0})
    span.end()

    spans = tracer.get_spans()
    assert len(spans) == 1
    record = spans[0]
    assert record.name == "operation_a"
    assert record.attributes["http.status"] == 200
    assert record.attributes["user.id"] == "usr_123"
    assert record.duration_ms >= 0.0


def test_in_memory_span_parent_child_hierarchy() -> None:
    """Verify child spans inherit the parent's trace_id and record parent_span_id."""
    tracer = InMemoryTracer()

    parent_span = tracer.start_span("parent_op")
    child_span = tracer.start_span("child_op", parent=parent_span)

    assert child_span.context.trace_id == parent_span.context.trace_id
    assert child_span.context.span_id != parent_span.context.span_id
    assert child_span.parent_span_id == parent_span.context.span_id

    child_span.end()
    parent_span.end()

    spans = tracer.get_spans()
    assert len(spans) == 2
    assert spans[0].name == "child_op"
    assert spans[1].name == "parent_op"


def test_in_memory_span_context_manager() -> None:
    """Verify sync context manager automatically sets and resets active context."""
    tracer = InMemoryTracer()

    assert get_current_span() is None
    assert get_current_context() is None

    with tracer.start_as_current_span("sync_span") as span:
        assert span is not None
        assert get_current_span() is span
        assert get_current_context() == span.context

        # Nested span automatically adopts active context as parent
        with tracer.start_as_current_span("nested_span") as nested:
            assert nested is not None
            assert nested.parent_span_id == span.context.span_id
            assert nested.context.trace_id == span.context.trace_id

    assert get_current_span() is None
    assert get_current_context() is None
    assert len(tracer.get_spans()) == 2


@pytest.mark.asyncio
async def test_in_memory_span_async_context_manager() -> None:
    """Verify async context manager automatically records exceptions and cleans up context."""
    tracer = InMemoryTracer()

    with pytest.raises(ValueError, match="Database error"):
        async with tracer.start_as_current_span("async_op"):
            raise ValueError("Database error")

    spans = tracer.get_spans()
    assert len(spans) == 1
    record = spans[0]
    assert record.status == SpanStatus.ERROR
    assert "Database error" in (record.error_message or "")
    assert len(record.events) == 1
    assert record.events[0]["exception.type"] == "ValueError"


def test_tracer_inject_and_extract_context() -> None:
    """Verify injection into carrier dict and extraction back to SpanContext."""
    tracer = InMemoryTracer()
    original_ctx = SpanContext(
        trace_id="1234567890abcdef1234567890abcdef",
        span_id="1234567890abcdef",
        trace_flags="01",
        trace_state="congo=2",
    )

    carrier: dict[str, str] = {}
    tracer.inject_context(carrier, context=original_ctx)

    assert "traceparent" in carrier
    assert (
        carrier["traceparent"]
        == "00-1234567890abcdef1234567890abcdef-1234567890abcdef-01"
    )
    assert carrier["tracestate"] == "congo=2"

    extracted_ctx = tracer.extract_context(carrier)
    assert extracted_ctx is not None
    assert extracted_ctx.trace_id == original_ctx.trace_id
    assert extracted_ctx.span_id == original_ctx.span_id
    assert extracted_ctx.trace_state == original_ctx.trace_state


# =====================================================================
# 4. Secret & PII Scrubber Tests
# =====================================================================


def test_secret_scrubber_text() -> None:
    """Verify redaction of Bearer tokens, Gemini keys, Tavily keys, and private keys in text."""
    raw_text = (
        "Received Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.token "
        "Gemini key AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q and "
        "Tavily key tvly-abcdefghijklmnopqrstuvwxyz123456. "
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
    )

    scrubbed = SecretScrubber.scrub_text(raw_text)
    assert "Bearer [REDACTED]" in scrubbed
    assert "[REDACTED_GEMINI_KEY]" in scrubbed
    assert "[REDACTED_TAVILY_KEY]" in scrubbed
    assert "[REDACTED_PRIVATE_KEY]" in scrubbed
    assert "AIzaSy" not in scrubbed
    assert "tvly-" not in scrubbed


def test_secret_scrubber_data_nested() -> None:
    """Verify recursive redaction of sensitive dictionary keys and values."""
    payload: dict[str, Any] = {
        "user": "alice",
        "api_key": "secret_api_key_12345",
        "password": "super_secret_password",
        "headers": {
            "Authorization": "Bearer some_jwt_token_here_12345",
            "Content-Type": "application/json",
        },
        "query": "Research goal with Gemini key AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q",
    }

    scrubbed = SecretScrubber.scrub_data(payload)
    assert scrubbed["user"] == "alice"
    assert scrubbed["api_key"] == "[REDACTED]"
    assert scrubbed["password"] == "[REDACTED]"
    assert scrubbed["headers"]["Authorization"] == "[REDACTED]"
    assert scrubbed["headers"]["Content-Type"] == "application/json"
    assert "[REDACTED_GEMINI_KEY]" in scrubbed["query"]


# =====================================================================
# 5. Structured JSON Log Formatter Tests
# =====================================================================


def test_structured_json_log_formatter() -> None:
    """Verify single-line JSON log formatting with trace correlation and scrubbing."""
    formatter = StructuredJsonLogFormatter(
        project_id="test-gcp-project", enable_scrubbing=True
    )
    record = logging.LogRecord(
        name="app.api.routes",
        level=logging.INFO,
        pathname="routes.py",
        lineno=42,
        msg="Invoked with key AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q",
        args=(),
        exc_info=None,
        func="create_run",
    )

    ctx = SpanContext(
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        span_id="00f067aa0ba902b7",
        trace_flags="01",
    )

    tracer = InMemoryTracer()
    with tracer.start_as_current_span("log_test", parent=ctx):
        output = formatter.format(record)

    data = json.loads(output)
    assert data["severity"] == "INFO"
    assert "[REDACTED_GEMINI_KEY]" in data["message"]
    assert (
        data["logging.googleapis.com/trace"]
        == "projects/test-gcp-project/traces/4bf92f3577b34da6a3ce929d0e0e4736"
    )
    assert data["logging.googleapis.com/spanId"] is not None
    assert data["logging.googleapis.com/trace_sampled"] is True


# =====================================================================
# 6. Metrics Accumulator & ObservabilityBridgeHook Tests
# =====================================================================


def test_metrics_accumulator() -> None:
    """Verify monotonic counters, duration histograms, and gauges."""
    metrics = InMemoryMetricsAccumulator()
    metrics.increment_counter("runs_started", 2)
    metrics.increment_counter("runs_completed", 1)
    metrics.increment_counter("runs_failed", 1)
    metrics.increment_counter("tasks_started", 5)
    metrics.increment_counter("tasks_completed", 4)
    metrics.increment_counter("tasks_failed", 1)
    metrics.increment_counter("tasks_retried", 2)
    metrics.increment_counter("tokens.prompt", 100)
    metrics.increment_counter("tokens.completion", 50)
    metrics.increment_counter("tokens.total", 150)
    metrics.set_gauge("active_runs", 1)
    metrics.record_histogram("run.duration_ms", 1250.0)
    metrics.record_histogram(
        "subtask.duration_ms", 450.0, attributes={"subtask_id": "task_1"}
    )

    summary: MetricSummary = metrics.get_summary()
    assert summary.total_runs_started == 2
    assert summary.total_runs_completed == 1
    assert summary.total_runs_failed == 1
    assert summary.total_tasks_started == 5
    assert summary.total_tasks_completed == 4
    assert summary.total_tasks_failed == 1
    assert summary.total_tasks_retried == 2
    assert summary.total_prompt_tokens == 100
    assert summary.total_completion_tokens == 50
    assert summary.total_tokens == 150
    assert summary.active_runs == 1
    assert summary.run_durations_ms == (1250.0,)
    assert summary.subtask_durations_ms["task_1"] == (450.0,)


@pytest.mark.asyncio
async def test_observability_bridge_hook() -> None:
    """Verify that ObservabilityBridgeHook correctly forwards DAG execution events to metrics."""
    metrics = InMemoryMetricsAccumulator()
    hook = ObservabilityBridgeHook(metrics=metrics)

    await hook.on_run_started("run_1", "plan_1")
    assert metrics.get_summary().active_runs == 1
    assert metrics.get_summary().total_runs_started == 1

    await hook.on_task_started("run_1", "subtask_1", 1)
    assert metrics.get_summary().total_tasks_started == 1

    await hook.on_task_completed(
        "run_1",
        "subtask_1",
        320,
        TokenUsage(prompt_tokens=40, completion_tokens=20, total_tokens=60),
    )
    assert metrics.get_summary().total_tasks_completed == 1
    assert metrics.get_summary().total_tokens == 60

    await hook.on_task_retried("run_1", "subtask_2", 2, 1.0)
    assert metrics.get_summary().total_tasks_retried == 1

    await hook.on_task_failed("run_1", "subtask_2", 2, "error", False)
    assert metrics.get_summary().total_tasks_failed == 1

    await hook.on_run_completed(
        "run_1",
        1.5,
        TokenUsage(prompt_tokens=40, completion_tokens=20, total_tokens=60),
    )
    assert metrics.get_summary().active_runs == 0
    assert metrics.get_summary().total_runs_completed == 1


# =====================================================================
# 7. Factory & Telemetry Provider Lifecycle Tests
# =====================================================================


def test_create_telemetry_provider_default() -> None:
    """Verify factory returns DefaultTelemetryProvider with InMemoryTracer by default."""
    provider = create_telemetry_provider()
    assert isinstance(provider.tracer, InMemoryTracer)
    assert isinstance(provider.metrics, InMemoryMetricsAccumulator)


def test_create_telemetry_provider_otel_fallback() -> None:
    """Verify factory handles otel_enabled=True gracefully and falls back when appropriate."""
    settings = AppSettings(
        OTEL_ENABLED=True,
        OTEL_SERVICE_NAME="test-service",
        OTEL_SAMPLING_RATIO=0.5,
    )
    provider = create_telemetry_provider(settings)
    assert provider.tracer is not None
    assert provider.metrics is not None


def test_global_telemetry_provider_helpers() -> None:
    """Verify get_tracer() and get_metrics() return singleton instances."""
    tracer = get_tracer()
    metrics = get_metrics()
    assert isinstance(tracer, TracerProtocol)
    assert isinstance(metrics, MetricsProtocol)
