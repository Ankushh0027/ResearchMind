# Phase 6.2 — Distributed Messaging & Task Distribution Implementation

## 1. Overview & Architecture

Phase 6.2 introduces a production-ready, provider-agnostic **Google Cloud Pub/Sub** distributed messaging transport for **ResearchMind**, replacing the single-process in-memory queue constraint for scalable multi-worker deployment while preserving the `InMemoryJobQueue` for local development and deterministic unit/integration testing.

### Messaging Topology & Component Architecture

```
                                  ┌───────────────────────────┐
                                  │      FastAPI Gateway      │
                                  │    (app/api/service.py)   │
                                  └─────────────┬─────────────┘
                                                │
                                   Publishes JobEnvelope
                                                │
                                                ▼
                                  ┌───────────────────────────┐
                                  │   JobPublisherProtocol    │
                                  └─────────────┬─────────────┘
                                                │
                     ┌──────────────────────────┴──────────────────────────┐
                     │                                                     │
           [JOB_TRANSPORT=in_memory]                              [JOB_TRANSPORT=pubsub]
                     ▼                                                     ▼
      ┌─────────────────────────────┐                       ┌─────────────────────────────┐
      │     InMemoryJobPublisher    │                       │    GooglePubSubPublisher    │
      └──────────────┬──────────────┘                       └──────────────┬──────────────┘
                     │                                                     │
              Async FIFO Queue                                  Publishes to GCP Topic:
                     │                                      `projects/{id}/topics/{topic}`
                     ▼                                                     │
      ┌─────────────────────────────┐                                      ▼
      │     InMemoryJobConsumer     │                       ┌─────────────────────────────┐
      └──────────────┬──────────────┘                       │    GCP Pub/Sub Subscription │
                     │                                      │ `projects/{id}/subs/{sub}`  │
                     │                                      └──────────────┬──────────────┘
                     │                                                     │
                     │                                            Pulls & Extends Lease
                     │                                                     │
                     │                                                     ▼
                     │                                      ┌─────────────────────────────┐
                     │                                      │    GooglePubSubConsumer     │
                     │                                      │   + AckDeadlineExtender     │
                     │                                      └──────────────┬──────────────┘
                     │                                                     │
                     └──────────────────────────┬──────────────────────────┘
                                                │
                                      Dispatches JobEnvelope
                                                │
                                                ▼
                                  ┌───────────────────────────┐
                                  │     ResearchJobWorker     │
                                  │    (app/jobs/worker.py)   │
                                  └─────────────┬─────────────┘
                                                │
                                 Idempotent Pipeline Execution
                               (Planner -> DAGExecutor -> Dossier)
                                                │
                                                ▼
                                  ┌───────────────────────────┐
                                  │    RunRepositoryProtocol  │
                                  │  (Firestore / InMemory)   │
                                  └───────────────────────────┘
```

---

## 2. Pub/Sub Publisher & Consumer Design

### Publisher (`GooglePubSubPublisher`)
- **Implements**: `JobPublisherProtocol` (`publish(envelope: JobEnvelope) -> str`).
- **Envelope Serialization**: Serializes `JobEnvelope` directly to JSON bytes.
- **Attributes Metadata**: Attaches message attributes:
  - `job_id`: Unique identifier of the job.
  - `run_id`: Associated research run identifier.
  - `attempt`: Current attempt counter string.
  - `idempotency_key`: Deduplication key formatted as `{job_id}_{attempt}`.
  - `status`: Lifecycle status (`QUEUED` or `DEAD_LETTERED`).
- **Async-Safe Execution**: Non-blocking publishing via asyncio thread executor / future resolution.
- **Dead-Letter Routing**: Includes dedicated `publish_dead_letter(envelope)` method targeting the configured DLQ topic.

### Consumer (`GooglePubSubConsumer`)
- **Implements**: `JobConsumerProtocol` (`start()`, `stop()`, `is_running()`).
- **Worker Pool**: Configurable worker concurrency pulling and processing messages asynchronously.
- **Poison-Pill Protection**: If a malformed, non-JSON, or schema-invalid payload is delivered, the consumer acknowledges the message (and logs error details) to prevent continuous poisonous redelivery.
- **Result Handling**:
  - `COMPLETED` / `CANCELLED`: Message is immediately acknowledged (`ack()`).
  - `FAILED` (Transient & `attempt < max_attempts`): Schedules next attempt with incremented attempt count (`attempt + 1`), resets execution timestamps, publishes to job topic, and acknowledges original message.
  - `FAILED` (Non-retryable or retries exhausted): Publishes to dead-letter topic (DLQ) with status `DEAD_LETTERED`, then acknowledges original message.
- **Graceful Shutdown**: Cancels worker tasks cleanly and negative-acknowledges unhandled in-flight messages so other consumers can immediately pick them up.

---

## 3. Acknowledgement Deadline Lease Extension (`AckDeadlineExtender`)

Research runs and multi-agent DAGs can execute for minutes, exceeding standard Google Cloud Pub/Sub default acknowledgement deadlines (typically 10–600s).

### Heartbeat Mechanism
- Upon message ingestion, an `AckDeadlineExtender` background task is instantiated for the message's `ack_id`.
- Every `heartbeat_interval_seconds` (default: 20s), it calls `subscriber_client.modify_ack_deadline(request={"subscription": sub_path, "ack_ids": [ack_id], "ack_deadline_seconds": ack_extension_seconds})`.
- When processing finishes (ACK, NACK, error, or task cancellation), `extender.stop()` cancels and awaits the background task in a `finally` block, ensuring no leaked coroutines or background tasks.

---

## 4. At-Least-Once Delivery & Idempotency Strategy

Google Cloud Pub/Sub provides **at-least-once message delivery**. Messages may be redelivered during transient network partitions or worker failovers.

### Deduplication & State Protection
1. **Terminal Stage Short-Circuiting**:
   - `ResearchJobWorker.handle_job` checks the associated `RunContext` and `RunRepository` record status prior to launching decomposition or DAG execution.
   - If the run is already in `RunStage.COMPLETED` or `RunStage.CANCELLED`, the worker immediately returns `JobStatus.COMPLETED` or `JobStatus.CANCELLED` without executing the DAG, invoking agents, or making duplicate LLM calls.
2. **Optimistic Locking**:
   - The persistence layer (`FirestoreRunRepository` and `InMemoryRunRepository`) validates `RunRecord.version` on every state transition, rejecting conflicting concurrent writes.
3. **Idempotency Keys**:
   - Every published message attaches an `idempotency_key` (`{job_id}_{attempt}`) enabling downstream telemetry, tracing, and deduplication auditing.

---

## 5. Configuration & Environment Variables

The application configuration in `app/config/settings.py` includes:

| Environment Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `JOB_TRANSPORT` | `Literal["in_memory", "pubsub"]` | `in_memory` | Active job messaging transport backend |
| `GCP_PROJECT_ID` | `str` | `researchmind-dev` | Google Cloud Project ID |
| `PUBSUB_TASKS_TOPIC` | `str` | `researchmind-agent-tasks` | Pub/Sub topic for dispatching asynchronous research jobs |
| `PUBSUB_TASKS_SUBSCRIPTION` | `str` | `researchmind-agent-tasks-sub` | Pub/Sub subscription for worker job ingestion |
| `PUBSUB_EVENTS_TOPIC` | `str` | `researchmind-workflow-events` | Pub/Sub topic for streaming workflow state events |
| `PUBSUB_DEAD_LETTER_TOPIC` | `str` | `researchmind-agent-tasks-dlq` | Pub/Sub topic for unrecoverable or exhausted jobs |
| `PUBSUB_MAX_ATTEMPTS` | `int` | `3` | Maximum allowed execution attempts before routing to DLQ |
| `PUBSUB_ACK_DEADLINE_SECONDS` | `int` | `60` | Pub/Sub message ack deadline lease in seconds |
| `PUBSUB_ACK_EXTENSION_SECONDS` | `int` | `60` | Lease extension period in seconds per heartbeat |
| `PUBSUB_EMULATOR_HOST` | `str \| None` | `None` | Host and port for local Pub/Sub emulator (e.g. `localhost:8085`) |

---

## 6. Factory Constructors & Dependency Injection

The `app.jobs.factory` module dynamically instantiates the correct publisher and consumer based on settings:

```python
from app.jobs.factory import create_job_consumer, create_job_publisher

# Automatically resolves based on JOB_TRANSPORT:
publisher = create_job_publisher()
consumer = create_job_consumer(handler=worker)
```

The service layer (`ResearchService`) and standalone worker runner (`StandaloneWorkerRunner`) rely exclusively on `JobPublisherProtocol` and `JobConsumerProtocol`.

---

## 7. Local Development & Production Deployment

### Local Development (Default)
- Keep `JOB_TRANSPORT=in_memory` (default). No external Pub/Sub emulator or GCP credentials required.

### Local Development with Pub/Sub Emulator
```bash
# Start Pub/Sub Emulator
gcloud beta emulators pubsub start --host-port=0.0.0.0:8085

# Configure environment
export JOB_TRANSPORT=pubsub
export PUBSUB_EMULATOR_HOST=localhost:8085
export GCP_PROJECT_ID=researchmind-dev
```

### Production GCP Deployment (Cloud Run / GKE)
```bash
export JOB_TRANSPORT=pubsub
export GCP_PROJECT_ID=my-prod-project
export PUBSUB_TASKS_TOPIC=researchmind-tasks-prod
export PUBSUB_TASKS_SUBSCRIPTION=researchmind-tasks-prod-sub
export PUBSUB_DEAD_LETTER_TOPIC=researchmind-tasks-dlq-prod
export PERSISTENCE_BACKEND=firestore
```

Credentials are automatically inherited via Google Cloud Workload Identity or attached Service Account with `roles/pubsub.publisher` and `roles/pubsub.subscriber`.

---

## 8. Verification & Test Coverage

- **Total Tests Passing**: 516
- **Test Suite**:
  - `backend/tests/unit/test_pubsub_jobs.py` (Publisher attributes, DLQ, Consumer processing, Poison pill protection, Retry exhaustion, Ack lease extension, Idempotent duplicate delivery, Missing library error).
  - `backend/tests/unit/test_job_factory.py` (Factory switching based on `JOB_TRANSPORT`).
  - `backend/tests/unit/test_config.py` (Pub/Sub configuration defaults and environment overrides).
  - `backend/tests/integration/test_async_job_e2e.py` (End-to-end multi-agent research run executed over `GooglePubSubPublisher` & `GooglePubSubConsumer`).
- **Quality Gates**:
  - Pytest: 516 passed in ~4.5s
  - Ruff: 0 errors
  - Ruff format: Clean (167 files formatted)
  - Mypy: 0 errors (153 source files checked)
