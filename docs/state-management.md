# State Management Specification

This document details the state schema, Firestore document structure, and concurrency control for research runs.

---

## 1. Firestore Data Model

### Collection: `research_runs`
Top-level document representing an overall research session.

- **Document ID**: `{run_id}` (e.g. `run_9f3b2a81`)
- **Fields**:
  - `run_id` (string): Unique identifier for the research execution.
  - `status` (string): Current state machine state (`CREATED`, `RUNNING`, `COMPLETED`, etc.).
  - `research_goal` (string): Original user query or research topic.
  - `plan` (map): Structured decomposition created by Planner Agent.
  - `current_stage` (string): Current active pipeline stage.
  - `retry_count` (int): Number of automatic retries attempted.
  - `error_details` (map | null): Structured error record if failed.
  - `created_at` (timestamp): Request ingestion timestamp.
  - `updated_at` (timestamp): Last state mutation timestamp.
  - `completed_at` (timestamp | null): Completion timestamp.
  - `artifact_uri` (string | null): GCS path to the final report artifact.

### Subcollection: `research_runs/{run_id}/tasks`
Individual subtask execution records.

- **Document ID**: `{subtask_id}` (e.g. `task_01`)
- **Fields**:
  - `subtask_id` (string): Task identifier within the plan.
  - `objective` (string): Objective of this specific inquiry branch.
  - `status` (string): `PENDING` | `IN_PROGRESS` | `COMPLETED` | `FAILED`.
  - `evidence_count` (int): Number of evidence items gathered.
  - `assigned_worker` (string): Worker instance identifier.
  - `heartbeat` (timestamp): Last worker heartbeat.

### Subcollection: `research_runs/{run_id}/evidence`
Extracted evidence items with provenance metadata.

- **Document ID**: `{evidence_id}`
- **Fields**:
  - `evidence_id` (string): Evidence record identifier.
  - `source_url` (string): Provenance URL.
  - `title` (string): Source title.
  - `snippet` (string): Extracted text quote.
  - `qdrant_point_id` (string): Vector ID in Qdrant.
  - `created_at` (timestamp): Extraction timestamp.

---

## 2. Concurrency & Optimistic Locking

- State updates use Firestore transactional writes or optimistic locking via `updated_at` version checks.
- When multiple parallel research workers write evidence to the same run, they append to the isolated `evidence` subcollection to eliminate lock contention on the parent run document.
