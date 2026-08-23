# ResearchMind Phase 6.1 — Durable State & Checkpoint Persistence

## 1. Overview & Architectural Boundary

In Phase 6.1, ResearchMind introduces a provider-agnostic durable persistence boundary, replacing in-memory state dictionaries with formal repository protocols while maintaining full backward compatibility for in-memory local testing.

```text
HTTP Client / Web App
        │
        ▼
FastAPI API Layer (`app.api.routes`)
        │
        ▼
ResearchService (`app.api.service`)
        │
   ┌────┴──────────────────────────┐
   ▼                               ▼
RunRepositoryProtocol       JobPublisherProtocol
(InMemory / Firestore)     (InMemory / Cloud Pub/Sub)
   │                               │
   │  ┌────────────────────────────┘
   │  ▼
ResearchJobWorker (`app.jobs.worker`)
   │
   ├──► CheckpointRepositoryProtocol (`app.persistence.protocols`)
   │       ├── InMemoryCheckpointRepository
   │       └── FirestoreCheckpointRepository
   │
   └──► DAGExecutor & Multi-Agent Mesh
```

---

## 2. Repository Protocol Hierarchy

The persistence system is organized around strongly-typed, runtime-checkable protocols located in `backend/app/persistence/protocols.py`:

1. **`RunRecord`**:
   - Immutable Pydantic model representing the complete lifecycle state of a research inquiry.
   - Includes goal query, lifecycle stage (`RunStage`), plan ID, subtask statuses, aggregated `TokenUsage`, execution duration, cancellation flags, and compiled `ResearchDossier`.
   - Supports monotonic versioning via `with_updates(..., increment_version=True)`.

2. **`RunRepositoryProtocol`**:
   - `async def create_run(record: RunRecord) -> RunRecord`
   - `async def get_run(run_id: str) -> RunRecord | None`
   - `async def update_run(record: RunRecord, expected_version: int | None = None) -> RunRecord`
   - `async def list_runs(limit: int = 50, offset: int = 0) -> list[RunRecord]`

3. **`CheckpointRepositoryProtocol`**:
   - `async def save_checkpoint(snapshot: CheckpointSnapshot) -> None`
   - `async def load_latest_checkpoint(run_id: str) -> CheckpointSnapshot | None`
   - `async def list_checkpoints(run_id: str) -> list[CheckpointSnapshot]`

4. **`EventRepositoryProtocol`**:
   - `async def emit_event(event: ExecutionEvent) -> None`
   - `async def get_events(run_id: str, after_index: int = 0) -> list[ExecutionEvent]`

---

## 3. Google Cloud Firestore Document Model & Schema

When `PERSISTENCE_BACKEND="firestore"` is configured, state is stored in Firestore with the following document structure:

### Collection: `research_runs` (Document ID: `{run_id}`)
```json
{
  "run_id": "run_94b8e21a8d01",
  "goal": {
    "goal_id": "goal_84ef11a2",
    "query": "Evaluate fault-tolerant quantum error correction thresholds",
    "domain_tags": ["physics", "quantum"],
    "constraints": {"max_depth": 3},
    "max_subtasks": 8,
    "schema_version": "1.0.0",
    "created_at": "2026-08-23T12:00:00Z"
  },
  "status": "COMPLETED",
  "plan_id": "plan_94b8e21a8d01",
  "completed_task_ids": ["task_01", "task_02", "task_03", "task_04"],
  "failed_task_ids": [],
  "cancelled_task_ids": [],
  "total_token_usage": {
    "prompt_tokens": 1420,
    "completion_tokens": 850,
    "total_tokens": 2270
  },
  "duration_seconds": 18.42,
  "dossier": {
    "dossier_id": "dossier_94b8e21a8d01",
    "run_id": "run_94b8e21a8d01",
    "goal_query": "Evaluate fault-tolerant quantum error correction thresholds",
    "methodology_summary": "Topological decomposition with literature cross-examination",
    "executive_summary": "Surface codes exhibit a ~1% error threshold under depolarizing noise.",
    "key_findings": [...],
    "claims": [...],
    "citations": [...],
    "contradictions": [...],
    "limitations": [],
    "confidence_rating": 0.96,
    "verification_status": "VERIFIED",
    "markdown_report": "# Research Report\n\n..."
  },
  "error": null,
  "is_cancelled": false,
  "cancellation_reason": null,
  "version": 4,
  "created_at": "2026-08-23T12:00:00Z",
  "updated_at": "2026-08-23T12:00:18Z"
}
```

### Collection: `research_checkpoints` (Document ID: `{run_id}_v{checkpoint_version:05d}`)
```json
{
  "snapshot_id": "snap_94b8e21a8d01_00002",
  "run_id": "run_94b8e21a8d01",
  "stage": "VERIFYING",
  "checkpoint_version": 2,
  "state_hash": "a4f8...SHA256",
  "state_payload": { ... },
  "created_at": "2026-08-23T12:00:10Z"
}
```

---

## 4. Optimistic Concurrency & Consistency Model

1. **Version Field**: Every `RunRecord` possesses a monotonically increasing integer `version` field.
2. **Version Checks on Mutation**:
   - `update_run(record, expected_version=N)` verifies that the existing document in the repository currently has version `N`.
   - If the version has already changed (due to a concurrent worker or API modification), the update fails immediately with `ValueError("Optimistic lock conflict...")`, preventing lost updates.
3. **Cryptographic Tamper Verification**:
   - Every `CheckpointSnapshot` computes and records `compute_state_hash(state_payload)`.
   - Upon retrieval, `snapshot.verify_integrity()` is validated before restoring workflow execution, ensuring checkpoints cannot be corrupted or tampered with in storage.

---

## 5. Local Development vs. Production Migration

| Environment | `PERSISTENCE_BACKEND` | `GCP_PROJECT_ID` | `FIRESTORE_EMULATOR_HOST` | Behavior |
| :--- | :--- | :--- | :--- | :--- |
| **Unit / CI Tests** | `in_memory` | `researchmind-dev` | `None` | Fast, hermetic in-memory dictionaries with zero GCP credentials required. |
| **Local Emulator** | `firestore` | `test-project` | `localhost:8080` | Real Firestore SDK communicating with local Firebase/Google Cloud emulator. |
| **Production Cloud** | `firestore` | `researchmind-prod` | `None` | Managed Google Cloud Firestore instance with IAM service account auth. |

---

## 6. Security Considerations

1. **Tenant & Run Isolation**: All documents are partitioned strictly by `run_id`.
2. **No Hardcoded Credentials**: Uses standard `GOOGLE_APPLICATION_CREDENTIALS` or Workload Identity on GCP Cloud Run.
3. **Zero Untyped Payloads**: All data is strictly validated via Pydantic (`extra="forbid"`) before writing and after reading from storage.
