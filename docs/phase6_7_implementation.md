# Phase 6.7 — Distributed OpenTelemetry Tracing, Structured Metrics & Observability

Phase 6.7 establishes a provider-agnostic, distributed observability and telemetry subsystem for ResearchMind. It delivers end-to-end W3C distributed tracing, structured Google Cloud Logging with automated credential/PII sanitization, and dimensional metric aggregation.

---

## 1. Architecture Overview

```
+-----------------------------------------------------------------------------------+
|                        Client Request (HTTP / REST API)                           |
+-----------------------------------------------------------------------------------+
                                        |
                 [1] W3C traceparent (or auto-generated trace_id)
                                        v
                    +---------------------------------------+
                    |        TraceContextMiddleware         |
                    |   - Extracts/Injects W3C context      |
                    |   - Creates root HTTP request span    |
                    |   - Injects X-Trace-ID & traceparent  |
                    +---------------------------------------+
                                        |
                 [2] TraceContext embedded into JobEnvelope
                                        v
                    +---------------------------------------+
                    |         Google Cloud Pub/Sub          |
                    |       JobEnvelope.traceparent         |
                    +---------------------------------------+
                                        |
                 [3] Context restored at Worker boundary
                                        v
                    +---------------------------------------+
                    |          ResearchJobWorker            |
                    |   - Activates span: "job.handle"      |
                    +---------------------------------------+
                                        |
                 [4] Subtask spans & telemetry emitted
                                        v
                    +---------------------------------------+
                    |             DAGExecutor               |
                    |      ObservabilityBridgeHook          |
                    |   - Subtask spans (Planner, Analyst,  |
                    |     Researcher, Verifier, Reporter)   |
                    |   - Records durations & token metrics |
                    +---------------------------------------+
                                        |
                 [5] Artifact Storage operations tracked
                                        v
                    +---------------------------------------+
                    |       ArtifactStorageProtocol         |
                    |   - GCS / In-Memory upload & download |
                    +---------------------------------------+
```

---

## 2. Core Protocols & Abstractions (`app.observability.protocols`)

ResearchMind maintains complete framework agnosticism by depending on protocols rather than concrete OpenTelemetry SDK types directly:

1. **`SpanProtocol`**:
   - Manages span execution lifecycle (`set_attribute`, `set_attributes`, `record_exception`, `set_status`, `end`).
   - Supports both synchronous (`with span:`) and asynchronous (`async with span:`) context managers.
   - Holds an immutable W3C [`SpanContext`](file:///c:/Users/Ankush/Desktop/ResearchMind/backend/app/observability/models.py).

2. **`TracerProtocol`**:
   - Defines factory methods for creating spans (`start_span`, `start_as_current_span`).
   - Provides async context inspection (`current_span`, `current_context`).
   - Implements carrier serialization (`inject_context`, `extract_context`).

3. **`MetricsProtocol`**:
   - Captures dimensional performance telemetry:
     - `increment_counter(name, value, attributes)`
     - `record_histogram(name, value, attributes)`
     - `set_gauge(name, value, attributes)`
     - `get_summary() -> MetricSummary`

4. **`TelemetryProviderProtocol`**:
   - Container uniting `tracer` and `metrics` implementations with lifecycle hooks (`shutdown()`).

---

## 3. Distributed Tracing & W3C Trace Context Propagation

### W3C `traceparent` Standard
ResearchMind uses standard W3C `traceparent` header strings:
```
00-{trace_id_32_hex}-{span_id_16_hex}-{trace_flags_2_hex}
```

### Propagation Flow
1. **HTTP Perimeter**: Incoming HTTP requests passing through [`TraceContextMiddleware`](file:///c:/Users/Ankush/Desktop/ResearchMind/backend/app/observability/middleware.py) have their `traceparent` header extracted (or generated if missing). Response headers include:
   - `X-Trace-ID`: 32-character hexadecimal trace identifier.
   - `traceparent`: Full W3C formatted header string.
2. **Job Boundary**: When [`ResearchService.create_and_start_run`](file:///c:/Users/Ankush/Desktop/ResearchMind/backend/app/api/service.py) enqueues a job, the active trace context is serialized into [`JobEnvelope.traceparent`](file:///c:/Users/Ankush/Desktop/ResearchMind/backend/app/jobs/protocols.py).
3. **Worker Boundary**: [`ResearchJobWorker.handle_job`](file:///c:/Users/Ankush/Desktop/ResearchMind/backend/app/jobs/worker.py) restores the trace context and links all subsequent DAG execution spans under the original trace.
4. **DAG Execution**: [`DAGExecutor`](file:///c:/Users/Ankush/Desktop/ResearchMind/backend/app/orchestration/executor.py) communicates with [`ObservabilityBridgeHook`](file:///c:/Users/Ankush/Desktop/ResearchMind/backend/app/observability/metrics.py) to capture start/completion/retry/failure events for each agent subtask.

---

## 4. Structured Google Cloud Logging & Secret Scrubbing

### Google Cloud Logging JSON Output
When [`StructuredJsonLogFormatter`](file:///c:/Users/Ankush/Desktop/ResearchMind/backend/app/observability/logging.py) is active, log lines are formatted as single-line JSON records containing:
- `timestamp`: RFC3339 UTC timestamp.
- `severity`: Standard GCP log severity (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`).
- `message`: Sanitized log message text.
- `logging.googleapis.com/trace`: Correlated GCP trace path (`projects/{project_id}/traces/{trace_id}`).
- `logging.googleapis.com/spanId`: 16-character hexadecimal span ID.
- `logging.googleapis.com/trace_sampled`: Boolean trace sampling indicator.
- `sourceLocation`: File name, line number, and function name.

### Automated Secret & PII Scrubbing
[`SecretScrubber`](file:///c:/Users/Ankush/Desktop/ResearchMind/backend/app/observability/logging.py) applies automated sanitization before text or data reaches log output or span attributes:
- **Authorization / Bearer Tokens**: `Bearer [a-zA-Z0-9_\-\.]+` -> `Bearer [REDACTED]`
- **Gemini API Keys**: `AIzaSy[A-Za-z0-9_\-]{33}` -> `[REDACTED_GEMINI_KEY]`
- **Tavily Search Keys**: `tvly-[A-Za-z0-9_\-]{16,}` -> `[REDACTED_TAVILY_KEY]`
- **Private Key Blocks**: `-----BEGIN ... PRIVATE KEY-----` -> `[REDACTED_PRIVATE_KEY]`
- **Sensitive Dictionary Keys**: Any dictionary key matching `password`, `api_key`, `secret`, `token`, or `authorization` has its value replaced with `[REDACTED]`.

---

## 5. Metrics Collection & Aggregation

[`InMemoryMetricsAccumulator`](file:///c:/Users/Ankush/Desktop/ResearchMind/backend/app/observability/metrics.py) captures real-time dimensional performance metrics:
- **Gauges**:
  - `active_runs`: Current in-flight research runs.
- **Monotonic Counters**:
  - `runs_started`, `runs_completed`, `runs_failed`, `runs_cancelled`
  - `tasks_started`, `tasks_completed`, `tasks_failed`, `tasks_retried`
  - `tokens.prompt`: Total prompt tokens consumed by LLM agents.
  - `tokens.completion`: Total completion tokens generated.
  - `tokens.total`: Combined token usage.
- **Histograms**:
  - `run.duration_ms`: End-to-end execution latency distribution.
  - `subtask.duration_ms`: Execution latency broken down by subtask ID.

---

## 6. Configuration & Environment Variables

| Variable | Type | Default | Description |
|---|---|---|---|
| `OTEL_ENABLED` | `bool` | `false` | Enable OpenTelemetry distributed tracing and metrics export |
| `OTEL_SERVICE_NAME` | `str` | `researchmind` | Logical service name for resource identification |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `str` | `http://localhost:4317` | OTLP collector gRPC/HTTP endpoint URL |
| `OTEL_SAMPLING_RATIO` | `float` | `1.0` | Trace sampling ratio between `0.0` (none) and `1.0` (all) |
| `LOG_PII_SCRUBBING_ENABLED` | `bool` | `true` | Enable automated regex sanitization of credentials in logs |

---

## 7. Graceful Degradation & Test Safety Guarantees

1. **Local Test Parity**: By default, `OTEL_ENABLED=false` uses `InMemoryTracer` and `InMemoryMetricsAccumulator`, guaranteeing 100% network independence and zero flakiness in CI.
2. **Fail-Safe Operation**: All telemetry methods catch and isolate exceptions. An exporter network timeout or collector failure will **never** interrupt or fail an ongoing research run.
3. **Optional OpenTelemetry**: If OpenTelemetry packages are not installed, `OpenTelemetryTracer` gracefully logs a warning and falls back to `InMemoryTracer` without raising an `ImportError`.
