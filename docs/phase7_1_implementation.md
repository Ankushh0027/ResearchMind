# Phase 7.1: Production Reliability, Worker Leases & Automatic Failure Recovery

---

## 1. Overview & Problem Statement

In distributed research execution across Google Cloud Run and Cloud Pub/Sub, worker instances can experience unexpected terminations due to Out-Of-Memory (OOM) killer events, spot instance preemptions, unhandled network partitions, or infrastructure node crashes.

Prior to Phase 7.1, ResearchMind supported durable checkpoints, retries, and cancellation, but lacked **explicit worker lease ownership** and **automated supervisor recovery**. If a worker vanished mid-execution, the research run remained stalled in an active stage (e.g. `RESEARCHING`, `ANALYZING`, `VERIFYING`) without automated resumption.

### Objectives Achieved in Phase 7.1:
1. **Explicit Lease Ownership Protocol**:
   - Every active worker acquires a time-bounded, monotonic lease (`WorkerLease`) before executing a research run.
   - Only the active lease holder can renew or cleanly release the lease.
   - All operations are protected by atomic compare-and-set semantics in memory and transactional CAS in Cloud Firestore.
2. **Asynchronous Background Heartbeat Renewal**:
   - `WorkerHeartbeat` maintains continuous background renewals at configured intervals (`WORKER_HEARTBEAT_INTERVAL_SECONDS=15`) with jitter and graceful cancellation.
   - Emits structured telemetry counters (`worker.heartbeat.success`, `worker.heartbeat.failed`, `worker.heartbeat.revoked`).
   - Executes revocation callbacks if the lease is lost or stolen.
3. **Automated Lease Supervisor & Stale Run Reaper**:
   - `LeaseSupervisor` periodically audits active research runs (`PLANNING`, `RESEARCHING`, `ANALYZING`, `VERIFYING`, `EVALUATING`, `REPORTING`).
   - Identifies expired leases where `lease_expires_at < utc_now()` and reclaims execution ownership.
   - Prevents split-brain races: duplicate supervisor claims are rejected via atomic compare-and-set locks.
   - Inspects durable checkpoints (`CheckpointSnapshot`), verifies cryptographic SHA-256 integrity, and transitions run state back to `QUEUED` with incremented `recovery_attempt`.
   - Republishes `JobEnvelope` carrying metadata references to the exact checkpoint version for seamless worker resumption.
4. **Resumption from Checkpoints**:
   - `ResearchJobWorker` inspects the recovered checkpoint and invokes `DAGExecutor.resume_from_checkpoint(...)`.
   - Resumes graph traversal from the exact completed subtask boundary, skipping already finished tasks and avoiding redundant token expenditures.
   - Fallback synthesis ensures `ResearchDossier` compile and GCS artifact upload even on partial recovery topologies.
5. **Crash-Loop & Cancellation Safeguards**:
   - Enforces `WORKER_MAX_RECOVERY_ATTEMPTS=3`. If a run repeatedly crashes across workers, the supervisor marks the run as `FAILED` with an exhaustive recovery error and suppresses republication.
   - Intercepts user cancellations: if a run was cancelled while a worker died, the supervisor transitions the run to `CANCELLED` and suppresses republication.

---

## 2. Architecture & State Transition Lifecycle

```text
       ┌──────────────────────────────┐
       │   API / Client Submission    │
       └──────────────┬───────────────┘
                      │ (Publish JobEnvelope)
                      ▼
         ┌─────────────────────────┐
         │     Pub/Sub / Queue     │
         └────────────┬────────────┘
                      │
                      ▼ (Worker Ingestion)
       ┌──────────────────────────────┐
       │   Worker Instance A          │
       │   Acquires WorkerLease       │
       │   Starts WorkerHeartbeat     │
       └──────────────┬───────────────┘
                      │
                      ├──────────────────────────┐
                      ▼ (Progress Updates)       ▼ (CRASH / OOM / Partition)
       ┌──────────────────────────────┐          ┌───────────────────────┐
       │ Saves CheckpointSnapshot     │          │  Worker A Dies        │
       │ (Tasks 1..K Completed)       │          │  Heartbeat Ceases     │
       └──────────────────────────────┘          └───────────┬───────────┘
                                                             │
                                                             ▼
                                                 [ Lease Expired: t > t_exp ]
                                                             │
       ┌─────────────────────────────────────────────────────┴────────────────┐
       │                     LeaseSupervisor (Periodic Audit)                 │
       │  1. Detects expired lease on active run.                             │
       │  2. Claims recovery atomically via CAS (prevents supervisor races).  │
       │  3. Verifies checkpoint integrity & increments recovery_attempt.     │
       │  4. Re-queues run & republishes JobEnvelope with checkpoint meta.    │
       └──────────────────────────────────┬───────────────────────────────────┘
                                          │
                                          ▼ (Re-published JobEnvelope)
       ┌──────────────────────────────────────────────────────────────────────┐
       │                     Worker Instance B                                │
       │  1. Ingests JobEnvelope (recovery_attempt = 1).                      │
       │  2. Acquires new WorkerLease & starts WorkerHeartbeat.               │
       │  3. Resumes DAG execution from CheckpointSnapshot.                   │
       │  4. Skips completed tasks 1..K, executes remaining pending tasks.    │
       │  5. Emits ResearchDossier & releases WorkerLease cleanly.            │
       └──────────────────────────────────────────────────────────────────────┘
```

---

## 3. Configuration & Environment Variables

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `WORKER_LEASE_ENABLED` | bool | `true` | Enables distributed worker lease acquisition and heartbeats. |
| `WORKER_HEARTBEAT_INTERVAL_SECONDS` | float | `15.0` | Interval between asynchronous worker lease renewal heartbeats. |
| `WORKER_LEASE_DURATION_SECONDS` | float | `60.0` | TTL duration for a worker lease before being deemed stale. |
| `WORKER_MAX_RECOVERY_ATTEMPTS` | int | `3` | Maximum automatic recovery attempts allowed before marking run FAILED. |
| `SUPERVISOR_SCAN_INTERVAL_SECONDS` | float | `30.0` | Interval between supervisor sweeps for stale/expired worker leases. |

---

## 4. Subsystem Components & Contracts

### 4.1. Worker Lease (`backend/app/jobs/lease.py`)
- `WorkerLease`: Immutable Pydantic model tracking `lease_id`, `run_id`, `worker_id`, `acquired_at`, `expires_at`, `version`, and `heartbeat_count`.
- `LeaseManagerProtocol`: Defines `acquire_lease`, `renew_lease`, `release_lease`, `get_lease`, `is_lease_expired`.
- `InMemoryLeaseManager`: Thread-safe / coroutine-safe in-memory lease store with atomic compare-and-set logic.
- `FirestoreLeaseManager`: Transaction-based Google Cloud Firestore implementation guaranteeing ACID lease operations without race conditions.

### 4.2. Worker Heartbeat (`backend/app/jobs/heartbeat.py`)
- `WorkerHeartbeat`: Background task renewing the active lease every `interval_seconds`.
- Handles graceful shutdown and dispatches `on_lease_lost` callbacks if renewal fails (e.g. lease stolen or expired).

### 4.3. Lease Supervisor (`backend/app/jobs/supervisor.py`)
- `LeaseSupervisor`: Scans active runs (`ACTIVE_RUN_STAGES = (PLANNING, RESEARCHING, ANALYZING, VERIFYING, EVALUATING, REPORTING)`).
- Atomically claims recovery on stale runs with a supervisor lease.
- Intercepts cancellations: transitions run to `CANCELLED` if requested without republishing.
- Exhausts retries: transitions run to `FAILED` if `recovery_attempt >= max_recovery_attempts`.
- Loads latest valid `CheckpointSnapshot`, sets run stage to `QUEUED`, and publishes recovery `JobEnvelope`.

### 4.4. Resilient Worker Execution (`backend/app/jobs/worker.py`)
- In `ResearchJobWorker.handle_job`:
  - Acquires lease and spawns heartbeat renewal loop.
  - Automatically detects existing valid checkpoints and executes `DAGExecutor.resume_from_checkpoint(...)`.
  - Bypasses duplicate planning stages when recovering mid-execution.
  - Releases lease and stops heartbeats in `finally:` block.

---

## 5. Verification & Test Coverage

### Test Suite Execution
- **Unit Tests**:
  - `backend/tests/unit/test_worker_leases.py`: 10 tests covering lease acquisition, renewal, conflict rejection, takeover of expired leases, owner validation, and heartbeat callbacks.
  - `backend/tests/unit/test_worker_supervisor.py`: 5 tests covering stale run reaping, checkpoint verification, max attempt exhaustion, cancellation handling, and duplicate claim race protection.
- **Integration Tests**:
  - `backend/tests/integration/test_worker_recovery_e2e.py`: 3 comprehensive tests simulating worker crash mid-execution, transparent takeover by secondary worker, permanent crash exhaustion, and cancellation interception.
- **Overall Suite**:
  - Full project test suite: **828 passed in 10.34s** (0 failures, 0 regressions across all 7.1 phases).
  - Ruff check: clean (0 errors).
  - Ruff format: clean (247 files formatted).
  - Mypy static typing: clean (0 errors across 223 source files).
  - Golden benchmark: 4/4 scenarios passed (Average Score: 0.9781).
  - Smoke test: 5/5 checks passed.
