# Phase 6.6 — Durable Artifact Storage using Google Cloud Storage (GCS)

## 1. Executive Summary

Phase 6.6 establishes a provider-agnostic durable artifact storage layer for ResearchMind. As autonomous research runs produce extensive deliverables (e.g. publication-ready Markdown dossiers, structured claim graphs, synthesized evidence matrices, checkpoint snapshots), storing raw multi-megabyte payloads directly inside document databases (such as Google Cloud Firestore) leads to document size limit contention (Firestore 1 MiB boundary), inflated query costs, and reduced indexing performance.

Phase 6.6 decouples the **metadata index** (retained in Firestore via `RunRecord.artifacts`) from the **durable blob payload** (stored in Google Cloud Storage or the deterministic in-memory store), providing end-to-end SHA-256 integrity verification, path traversal security, and authenticated API access.

---

## 2. Architecture & Component Design

```
+-----------------------------------------------------------------------------------+
|                            Research Execution Workflow                            |
+-----------------------------------------------------------------------------------+
                                        |
                          [1] ResearchDossier Compiled
                                        |
                                        v
                    +---------------------------------------+
                    |        ArtifactStorageProtocol        |
                    +---------------------------------------+
                     /                                     \
                    v                                       v
      +----------------------------+         +----------------------------+
      |   InMemoryArtifactStorage  |         |     GCSArtifactStorage     |
      |   - Deterministic offline  |         |   - Google Cloud Storage   |
      |   - SHA-256 integrity check|         |   - Retry backoff logic    |
      |   - Thread-safe memory map |         |   - Custom blob metadata   |
      +----------------------------+         +----------------------------+
                    \                                       /
                     \-----------------   -----------------/
                                       \ /
                                        v
                    +---------------------------------------+
                    |       ArtifactMetadata Reference      |
                    |   (artifact_id, sha256, uri, size)    |
                    +---------------------------------------+
                                        |
                        [2] Persist Metadata in Index
                                        v
                    +---------------------------------------+
                    |      Firestore / InMemoryRunRepo      |
                    |        RunRecord.artifacts tuple      |
                    +---------------------------------------+
                                        |
                        [3] Cross-Service Instance Fetch
                                        v
                    +---------------------------------------+
                    |          FastAPI REST API             |
                    |  GET /api/v1/runs/{id}/artifacts      |
                    |  GET /api/v1/runs/{id}/artifacts/{aid}|
                    +---------------------------------------+
```

### Core Abstractions

1. **`ArtifactType`** (`backend/app/storage/models.py`):
   - `REPORT_MARKDOWN`: Final formatted Markdown deliverable (`report.md`).
   - `DOSSIER_JSON`: Complete structured `ResearchDossier` deliverable (`dossier.json`).
   - `CHECKPOINT_SNAPSHOT`: Execution checkpoint state dumps (`checkpoint.json`).
   - `EVIDENCE_BUNDLE`: Raw evidence documents, search dumps, and embeddings.
   - `OTHER`: Unclassified binary or text artifacts.

2. **`ArtifactMetadata`** (`backend/app/storage/models.py`):
   - Immutable Pydantic model (`frozen=True`) storing artifact identity, run association, canonical storage URI, MIME content type, byte size, SHA-256 digest, creation timestamp, schema version, and custom metadata dictionary.

3. **`ArtifactStorageProtocol`** (`backend/app/storage/protocols.py`):
   - Standard runtime-checkable interface defining asynchronous `upload`, `download`, `exists`, and `delete` primitives with SHA-256 integrity enforcement.

4. **`InMemoryArtifactStorage`** (`backend/app/storage/in_memory.py`):
   - Fast, thread-safe in-memory blob store for test suites, CI runners, and offline development.

5. **`GCSArtifactStorage`** (`backend/app/storage/gcs.py`):
   - Production adapter integrating with `google-cloud-storage`. Encapsulates client initialization, object key scoping, GCS custom metadata tagging (`x-goog-meta-sha256`), and exponential backoff retry on transient 5xx/connection errors.

6. **`create_artifact_storage`** (`backend/app/storage/factory.py`):
   - Factory function dynamically instantiating the appropriate backend based on `ARTIFACT_STORAGE_PROVIDER` configuration (`in_memory` or `gcs`).

---

## 3. Storage Security & Path Traversal Protection

All artifact object keys are treated as untrusted user-supplied input and validated via `validate_object_key(run_id, object_key)` (`backend/app/storage/security.py`) before interacting with any storage backend:

- **Path Traversal Guards**: Rejects directory traversal sequences (`..`, `../`, `/../`).
- **Path Sanitization**: Rejects leading slashes `/` and Windows backslashes `\`.
- **Character Allowlist**: Enforces regex validation `^[a-zA-Z0-9_\-\.]+$` on each path segment.
- **Control Character Detection**: Rejects null bytes (`\x00`) and characters with ASCII codes < 32.
- **Length Caps**: Caps object key lengths to 1024 characters.

---

## 4. Checksum Integrity Model

Every upload calculates an authoritative SHA-256 checksum over the raw payload bytes:
- On `upload(...)`: The SHA-256 hex digest is computed and saved in `ArtifactMetadata.sha256` and GCS blob metadata.
- On `download(...)`: When `verify_checksum=True` (default), the downloaded payload is re-hashed. If the computed hash does not match `ArtifactMetadata.sha256`, a `ChecksumMismatchError` is raised immediately before the corrupt payload reaches the application layer.

---

## 5. API Endpoints

All artifact endpoints are protected by the Phase 6.5 `verify_api_key` dependency:

| Endpoint | Method | Response | Description |
|---|---|---|---|
| `/api/v1/runs/{run_id}/artifacts` | `GET` | `list[ArtifactMetadata]` | Lists all artifact references for a run |
| `/api/v1/runs/{run_id}/artifacts/{artifact_id}` | `GET` | Raw Content Bytes | Streams artifact payload with `ETag` SHA-256 header |
| `/api/v1/runs/{run_id}/artifacts/{artifact_id}/metadata` | `GET` | `ArtifactMetadata` | Returns metadata and SHA-256 digest |

---

## 6. Configuration & Environment Variables

| Variable | Type | Default | Description |
|---|---|---|---|
| `ARTIFACT_STORAGE_PROVIDER` | `str` | `in_memory` | Backend provider: `in_memory` or `gcs` |
| `GCS_BUCKET` | `str` | `researchmind-artifacts` | Target GCS bucket name |
| `GCS_PROJECT` | `str | None` | `None` | GCP project ID (defaults to `GCP_PROJECT_ID`) |
| `GCS_PREFIX` | `str` | `artifacts` | Top-level folder prefix in bucket |
| `GCS_SIGNED_URL_EXPIRATION_SECONDS` | `int` | `3600` | Expiration for signed URLs (seconds) |

---

## 7. Known Limitations & Production Notes

1. **Direct GCS Streaming vs Server Proxying**: Currently, `GET /api/v1/runs/{id}/artifacts/{aid}` streams the blob through the FastAPI service layer. For massive evidence dumps (> 100 MiB), generation of direct GCS signed URLs can be leveraged to offload egress bandwidth.
2. **Offline Fallback**: In development and test environments where GCP service account credentials are unavailable, `ARTIFACT_STORAGE_PROVIDER=in_memory` provides full functional parity without external network dependencies.
