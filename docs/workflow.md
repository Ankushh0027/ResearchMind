# Asynchronous Workflow & Lifecycle Contract

This document outlines the asynchronous state machine, lifecycle transitions, and fault-tolerance semantics for ResearchMind research runs.

---

## 1. Lifecycle State Machine

A research run progresses through a formal finite state machine (FSM). Each state transition is persisted atomically to Google Cloud Firestore.

```
       [CREATED]
           │
           ▼
       [QUEUED]
           │
           ▼
       [RUNNING]
           │
           ├──► [PLANNING]
           │        │
           ├──► [RESEARCHING] ◄────┐ (Self-correction / additional research loop)
           │        │              │
           ├──► [ANALYZING]        │
           │        │              │
           ├──► [VERIFYING] ───────┤ (If contradiction or missing evidence detected)
           │        │
           ├──► [EVALUATING]
           │        │
           └──► [REPORTING]
                    │
                    ▼
               [COMPLETED]
```

### Exceptional & Terminal Failure States
At any non-terminal state, a run or subtask may transition to:
- `RETRYING`: Transient error encountered; awaiting exponential backoff delay before re-executing.
- `FAILED`: Unrecoverable error encountered (e.g. invalid query, exceeded retry limits, quota exhaustion).
- `CANCELLED`: User explicitly aborted the research run.

---

## 2. Detailed State Descriptions

| State | Description | Persistence Action |
| :--- | :--- | :--- |
| `CREATED` | Research request received and validated by the API Gateway. | Write initial run document in Firestore. |
| `QUEUED` | Job dispatched to Pub/Sub topic awaiting available worker instance. | Record message ID and queue timestamp. |
| `RUNNING` | Orchestration worker claimed the job and began execution. | Record worker ID and heartbeat lease. |
| `PLANNING` | Planner Agent decomposing goal into subtasks and search graph. | Save generated task plan and DAG nodes. |
| `RESEARCHING` | Parallel worker agents executing queries, scraping, and indexing evidence. | Commit collected evidence records and vector points. |
| `ANALYZING` | Analyst Agent synthesizing evidence and extracting key claims. | Commit draft structured findings. |
| `VERIFYING` | Verifier Agent validating claims, citations, and conflict checks. | Commit verification audit trail. |
| `EVALUATING` | Evaluator Agent assessing report quality, coherence, and goal coverage. | Record rubric scores and self-critique feedback. |
| `REPORTING` | Reporter Agent rendering final markdown/PDF artifact. | Upload artifact to GCS and store download URI. |
| `COMPLETED` | Execution successfully finished and final artifact delivered. | Mark run status as `COMPLETED`. |
| `RETRYING` | Recoverable error occurred; backoff timer active. | Update retry counter and schedule next attempt. |
| `FAILED` | Terminal failure condition reached. | Record structured error details and stack trace. |
| `CANCELLED` | Aborted upon client request. | Revoke running subtasks and mark cancelled. |

---

## 3. Durability & Process Restart Resilience

1. **State Persistence Across Restarts**: 
   - No workflow state is held exclusively in worker RAM.
   - All intermediate outputs (plans, evidence items, verified claims) are written to Firestore as they complete.
   - If a Cloud Run container or worker process crashes, another worker picks up the job by reading the latest snapshot from Firestore and resuming from the last uncompleted subtask.

2. **Heartbeat & Lease Management**:
   - Running workers periodically update a heartbeat timestamp on the active run record.
   - A supervisor monitor detects stale heartbeats (e.g., worker container killed due to out-of-memory) and transitions the job to `RETRYING` for reallocation.

3. **Pub/Sub Acknowledgement Semantics**:
   - Messages are acknowledged only after the state transition is successfully committed to Firestore.
   - In case of worker death during processing, the unacknowledged message is redelivered after the ack deadline expires.

---

## 4. Execution Engine & Scheduling Semantics

1. **Topological Task Scheduling**:
   - Tasks with zero unsatisfied prerequisite dependencies are eligible for immediate dispatch.
   - Dependent nodes (e.g., `Analyst` awaiting multiple parallel `Researcher` queries) remain blocked until all upstream dependencies reach `COMPLETED` status.
   - Runnable selection is deterministic (lexicographically ordered by `subtask_id`).

2. **Concurrent Task Dispatching**:
   - Parallel tasks execute asynchronously bounded by a configurable `max_concurrency` semaphore.
   - Task completion triggers state checkpoints and unlocks downstream dependent nodes.

3. **Exponential Backoff & Retries**:
   - Transient failures trigger retries with exponential backoff: $\text{delay} = \min(\text{base\_delay} \times 2^{\text{attempt}-2}, \text{max\_delay})$.
   - Non-retryable errors or retry-exhausted tasks transition to `FAILED`.

4. **Cooperative Cancellation**:
   - `CancellationToken` enables graceful shutdown of active executions.
   - Cancelling a run marks uncompleted tasks as `CANCELLED` and terminates the run state in `RunStage.CANCELLED`.

5. **Deadlock Prevention**:
   - If uncompleted tasks remain but zero tasks are runnable and zero workers are active, the engine raises `DeadlockDetectedError` and records a structured failure event.
