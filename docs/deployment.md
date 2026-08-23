# Google Cloud Deployment & Production Architecture

This document describes the deployment topology, container configuration, runtime process models, and cloud infrastructure components for hosting ResearchMind on Google Cloud Platform and local container environments.

---

## 1. Cloud Infrastructure Architecture

```text
Internet / Client
      │
      ▼
Google Cloud Armor (DDoS & WAF Protection)
      │
      ▼
Google Cloud Run (API Gateway Service)
      ├── Process: uvicorn app.api.app:create_app --factory
      ├── Autoscale: 0 -> 20 instances
      ├── Ingress: Load Balanced HTTPS
      ├── Health Probe: GET /healthz
      │
      ├── Write: Google Cloud Firestore (Run state & task trees)
      ├── Publish: Google Cloud Pub/Sub (`researchmind-agent-tasks`)
      └── Read: Google Cloud Storage (Final report artifacts)

Google Cloud Pub/Sub Topic (`researchmind-agent-tasks`)
      │
      ▼ (Push / Pull Subscription)
Google Cloud Run (Agent Worker Service / Job)
      ├── Process: python -m app.jobs.main
      ├── Autoscale: 0 -> 50 instances
      ├── Concurrency: Controlled via WORKER_CONCURRENCY
      │
      ├── Gemini 2.5 API (Vertex AI / Google AI Studio)
      ├── Qdrant Cloud (Vector Similarity Retrieval)
      ├── Write: Google Cloud Firestore (Evidence & Checkpoints)
      └── Write: Google Cloud Storage (`researchmind-artifacts`)
```

---

## 2. Infrastructure as Code & Service Layout

| Service | GCP Resource | Description |
| :--- | :--- | :--- |
| **API Gateway** | Cloud Run (Service) | FastAPI application exposing REST and SSE streaming endpoints. |
| **Agent Workers** | Cloud Run (Worker / Job) | Background consumer processing asynchronous research tasks. |
| **Message Queue** | Cloud Pub/Sub | Distributes tasks and streams progress events. |
| **State Store** | Cloud Firestore | Manages relational-like hierarchical research states and lock leases. |
| **Vector DB** | Qdrant Cloud / Compute Engine | Stores and queries high-dimensional embeddings for RAG. |
| **Object Store** | Cloud Storage (GCS) | Holds generated markdown/PDF research reports and raw source snapshots. |
| **Secret Store** | Cloud Secret Manager | Securely stores Gemini API keys and database credentials. |

---

## 3. Container Runtime Specifications

### 3.1 Base Image & Security
* **Base Image**: `python:3.12-slim`
* **Non-Root Execution**: Unprivileged runtime user `appuser` (UID 10001).
* **Layer Caching**: `pyproject.toml` and dependencies installed in dedicated intermediate layer.
* **Deterministic Environment**: Bytecode generation disabled (`PYTHONDONTWRITEBYTECODE=1`), unbuffered stdout/stderr (`PYTHONUNBUFFERED=1`).
* **Minimal Attack Surface**: Build tools, development caches, git metadata, and tests excluded via `.dockerignore`.

### 3.2 Building the Production Container

```bash
docker build -t researchmind:latest .
```

### 3.3 Production API Startup

```bash
docker run -p 8080:8080 \
  -e APP_ENV=production \
  -e PORT=8080 \
  -e LOG_LEVEL=INFO \
  researchmind:latest
```

Direct command executed inside container:
```bash
python -m uvicorn app.api.app:create_app --factory --host 0.0.0.0 --port 8080
```

### 3.4 Standalone Worker Startup

```bash
docker run \
  -e APP_ENV=production \
  -e WORKER_CONCURRENCY=4 \
  -e MAX_ORCHESTRATION_CONCURRENCY=8 \
  researchmind:latest python -m app.jobs.main
```

---

## 4. Local Multi-Service Simulation (Docker Compose)

A complete local production topology is defined in `docker-compose.yml`:

```bash
docker compose up --build
```

Services:
1. `api`: Exposes port 8080 with built-in health checking.
2. `worker`: Runs the standalone background worker loop.

---

## 5. Health, Readiness & Graceful Shutdown

* **Health Endpoint**: `GET /healthz` returns `{"status": "ok", "version": "0.1.0", "timestamp": "..."}` without requiring external authentication.
* **OpenAPI Specification**: `GET /openapi.json` and interactive docs at `/docs`.
* **Graceful Shutdown**: On `SIGTERM` / `SIGINT`, FastAPI lifespan and worker runner drain active requests and flush in-flight jobs up to `GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS` (default: 30s) before terminating.

---

## 6. Pub/Sub Boundary & Production Evolution

* **Phase 5.2 Local Architecture**: Uses `InMemoryJobQueue`, `InMemoryJobPublisher`, and `InMemoryJobConsumer` for deterministic in-process / integration test execution.
* **Distributed Cloud Architecture (Phase 5.3+)**:
  - `JobPublisherProtocol` wraps Google Cloud Pub/Sub client publishing serialized `JobEnvelope` messages to `PUBSUB_TASKS_TOPIC`.
  - `JobConsumerProtocol` runs on Cloud Run worker instances subscribing to `PUBSUB_TASKS_SUBSCRIPTION` via streaming pull or push endpoints.
  - State persistence shifts from `InMemoryCheckpointRepository` to Cloud Firestore.
  - In-memory queues cannot span separate container processes; the provider-agnostic protocol boundary allows swapping transport without modifying agent or orchestration logic.
