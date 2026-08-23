# Phase 5.2 — Asynchronous Job Consumer & Pub/Sub Worker Gateway

## 1. Overview & Architecture

Phase 5.2 establishes a durable, asynchronous job processing boundary separating the FastAPI API Gateway layer from the multi-agent execution engine (`DAGExecutor` + `AgentWorkerRouter`).

```
HTTP Client
   │
   ▼
FastAPI POST /api/v1/runs
   │
   ▼
ResearchService
   │
   ▼
JobPublisherProtocol (InMemoryJobPublisher)
   │
   ▼
JobEnvelope (FIFO Queue)
   │
   ▼
JobConsumerProtocol (InMemoryJobConsumer)
   │
   ▼
ResearchJobWorker (JobHandlerProtocol)
   │
   ├──► 1. PlannerWorker (Decomposes research goal into DAG)
   ├──► 2. DAGExecutor (Coordinates concurrent task execution)
   ├──► 3. AgentWorkerRouter (Dispatches to specialized workers)
   └──► 4. ResearchDossier (Attached to RunContext)
```

---

## 2. Core Job Contracts (`app.jobs.protocols`)

### 2.1 `JobEnvelope`
Immutable execution record encapsulating all necessary metadata for a research job:
- `job_id`: Globally unique job identifier.
- `run_id`: Associated research run identifier.
- `goal_query`: Raw inquiry string.
- `domain_tags`: Semantic domain tags (e.g. `['quantum-computing', 'physics']`).
- `constraints`: Operational constraints.
- `max_subtasks`: Upper limit on decomposed tasks.
- `attempt`: Current execution attempt (1-indexed).
- `max_attempts`: Upper limit on retry attempts before dead-letter routing (default: 3).
- `status`: `JobStatus` state.
- `is_retryable`: Error classification indicating whether failure warrants retry.
- `created_at`, `started_at`, `completed_at`: Monotonic and wall-clock telemetry timestamps.

### 2.2 `JobStatus`
- `QUEUED`: Enqueued awaiting consumer pickup.
- `RUNNING`: Claimed by consumer worker and currently executing.
- `COMPLETED`: Workflow successfully finished and `ResearchDossier` compiled.
- `FAILED`: Failure encountered during execution.
- `CANCELLED`: Client requested cancellation.
- `DEAD_LETTERED`: Terminal unrecoverable state reached after exhausting retries or encountering non-retryable error.

---

## 3. Reliability & Retry Semantics

1. **Transient Failures**:
   - Errors marked `is_retryable=True` (e.g., transient network/timeout glitches) re-enqueue the `JobEnvelope` with `attempt = attempt + 1`.
2. **Non-Retryable Errors**:
   - Invalid payloads, schema violations, permission denials, and DAG validation failures are marked `is_retryable=False` and immediately transition to `DEAD_LETTERED`.
3. **Retry Exhaustion**:
   - When `attempt >= max_attempts`, the job transitions to `DEAD_LETTERED` and is appended to `dead_letter_queue`.

---

## 4. Cancellation & Isolation Boundaries

- **Scoping**: `CancellationToken` is bound strictly to `run_id`.
- **Early Cancellation**: Before executing `PlannerWorker` or `DAGExecutor`, `ResearchJobWorker` checks cancellation state and exits cleanly without running unnecessary workers.
- **Tenant Isolation**: Jobs maintain independent event sinks, checkpoint repositories, and `RunContext` instances. No cross-run state leakage occurs.

---

## 5. Migration Path to Cloud Pub/Sub (Phase 5.3+)

The provider-agnostic `JobPublisherProtocol`, `JobConsumerProtocol`, and `JobHandlerProtocol` allow drop-in replacement with:
- `GoogleCloudPubSubPublisher` publishing to GCP Pub/Sub topics.
- `GoogleCloudPubSubConsumer` receiving push/pull subscriptions on Cloud Run workers.
