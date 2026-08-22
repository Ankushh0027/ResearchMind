# ResearchMind Architecture Specification

This document details the system design, communication patterns, and architectural principles underlying ResearchMind.

---

## 1. System Overview & Flow

ResearchMind is designed as an event-driven, micro-orchestrated autonomous multi-agent platform for deep research. It decomposes complex research inquiries into structured, parallel tasks, gathers empirical evidence, cross-checks contradictory facts, and evaluates synthesis quality before producing final reports.

```
User
  │
  ▼
API Gateway (FastAPI on Cloud Run)
  │  (Creates research run record, initializes state in Firestore)
  ▼
Orchestration Engine / Taskmaster
  │  (Publishes tasks to Google Cloud Pub/Sub / Async Worker Pool)
  ├──► Planner Agent (Decomposes research goal into inquiry plan & subtasks)
  │
  ├──► Parallel Research Workers (Execute concurrent subtasks)
  │      ├── Tool Execution (Web scraping, academic APIs, document extractors)
  │      └── RAG / Data Agent (Indexes chunks & embeddings into Qdrant)
  │
  ├──► Analyst Agent (Extracts claims, synthesizes multi-source evidence)
  │
  ├──► Conflict Detection & Verifier Agent (Cross-examines claims, detects contradictions)
  │
  ├──► Evaluator Agent (Evaluates report completeness, performs self-critique)
  │
  └──► Reporter Agent (Compiles final dossier and exports to Google Cloud Storage)
```

---

## 2. Core Architectural Components

### 2.1 API Gateway
- Serves as the public ingestion point for research requests.
- Performs initial input validation, rate limiting, and authentication.
- Persists the initial research session state into **Google Cloud Firestore**.
- Dispatches execution tasks to **Google Cloud Pub/Sub** topics.
- Provides SSE (Server-Sent Events) and REST polling endpoints for real-time run progress.

### 2.2 Taskmaster / Orchestration Engine (`app.orchestration`)
- **DAGScheduler**: Performs dependency-aware topological scheduling, determining runnable tasks whose prerequisite dependencies are satisfied.
- **DAGExecutor**: Coordinates asynchronous concurrent execution with bounded concurrency (`max_concurrency`), timeouts, retries, and checkpointing.
- **Deadlock Detection**: Detects unresolvable graph deadlocks and produces structured failures rather than hanging.
- **Cooperative Cancellation**: Halts scheduling of new tasks and gracefully cancels in-flight workers.

### 2.3 Agent Mesh

| Component | Role & Scope |
| :--- | :--- |
| **Planner Agent** | Analyzes research goals, identifies required domains, formulates targeted sub-questions, and generates execution plans. |
| **Research Agent** | Executes search queries, scrapes web resources, parses technical documents, and extracts raw candidate evidence. |
| **RAG / Data Agent** | Manages document chunking, semantic vector generation via Gemini embeddings, and similarity retrieval via Qdrant. |
| **Analyst Agent** | Synthesizes evidence gathered across multiple tasks, identifies key themes, and extracts factual assertions. |
| **Conflict Detection & Verifier Agent** | Maps claim-to-evidence relationships, identifies contradictory claims across different sources, and computes verification confidence scores. |
| **Evaluator Agent** | Self-critiques the draft research report against the original inquiry scope, identifying logical gaps, ungrounded assertions, or missing perspectives. |
| **Reporter Agent** | Compiles verified findings into publication-ready deliverables (Markdown/PDF), complete with verifiable citations, metadata, and executive summaries. |

---

## 3. Reliability & Resilience Principles

### 3.1 Persistent State & Checkpoints
All workflow state mutations produce immutable `CheckpointSnapshot` records containing:
- Run ID & Task ID
- Monotonically increasing checkpoint version
- Cryptographic SHA-256 state hash ensuring data integrity
- Full serialized state payload enabling zero-loss recovery across process restarts

### 3.2 Idempotency
- Every subtask execution request generates a deterministic `idempotency_key` (e.g. `idem_{run_id}_{subtask_id}_att{attempt}`).
- Duplicate messages or repeated worker deliveries do not cause duplicate state mutations or duplicate logical task completion.

### 3.3 Retries & Exponential Backoff
- `RetryPolicy` calculates backoff delays: $\text{delay} = \min(\text{base\_delay} \times \text{factor}^{\text{attempt}-2}, \text{max\_delay})$.
- Distinguishes between retryable errors (transient timeouts, rate limits) and non-retryable errors (schema violations, permission rejections).

### 3.4 Deadlock & Failure Recovery
- State machines are crash-resilient.
- If uncompleted tasks exist but no tasks are runnable and no workers are active, `DeadlockDetectedError` terminates the run cleanly without infinite waiting.
- `DAGExecutor.resume_from_checkpoint()` restores completed task states and resumes execution strictly on pending subtasks.

---

## 4. Observability & Telemetry

- **Typed Execution Events**: `RunStartedEvent`, `TaskScheduledEvent`, `TaskStartedEvent`, `TaskCompletedEvent`, `TaskFailedEvent`, `TaskRetryScheduledEvent`, `TaskCancelledEvent`, `RunCompletedEvent`, `RunFailedEvent`, `DeadlockDetectedEvent`.
- **Metrics & Auditing**: `ObservabilityHooksProtocol` hooks record durations, retry statistics, and token consumption (`prompt_tokens`, `completion_tokens`, `total_tokens`).

---

## 5. Security & Isolation Boundaries

- **Least Privilege Access**: `SecurityPolicy` validates agent tool permissions prior to dispatching task requests.
- **Untrusted Content Sanitization**: External text is wrapped in `UntrustedContentEnvelope` with XML delimiters and control-token neutralization.
- **Default-Deny Model**: Unknown roles or ungranted tool permissions raise `PermissionDeniedError`.

---

## 6. Worker Abstraction & Future Adapter Boundary

The orchestration layer remains strictly framework-agnostic through the `WorkerProtocol`:

```python
class WorkerProtocol(Protocol):
    async def execute(self, request: AgentRequest) -> WorkerResponseEnvelope: ...
```

This clean boundary allows future integration of:
- `MockWorker` (in-memory deterministic testing)
- `GeminiWorker` (direct Gemini API multi-agent reasoning)
- `GoogleADKWorker` (Google Agent Development Kit workflow adapter)

without modifying the core DAG scheduling or state machine engine.
