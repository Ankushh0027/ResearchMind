# Phase 5.3 — Production Containerization & Cloud Deployment Topology

## 1. Overview & Objectives

Phase 5.3 establishes a reproducible, production-grade container runtime and cloud deployment topology for ResearchMind while preserving the asynchronous job boundary introduced in Phase 5.2.

```text
HTTP Client / Cloud Armor
   │
   ▼
FastAPI API Service (Cloud Run / Container)
   │  [Entrypoint: uvicorn app.api.app:create_app --factory]
   ▼
ResearchService
   │
   ▼
JobPublisherProtocol
   │
   ▼
JobEnvelope (Task Transport Boundary)
   │
   ▼
JobConsumerProtocol / StandaloneWorkerRunner (Cloud Run / Container)
   │  [Entrypoint: python -m app.jobs.main]
   ▼
ResearchJobWorker
   │
   ├──► PlannerWorker
   ├──► DAGExecutor
   └──► AgentWorkerRouter -> ResearchDossier
```

---

## 2. Production Artifacts Implemented

### 2.1 Configuration Layer (`app.config.settings`)
* Strongly-typed Pydantic `BaseSettings` (`AppSettings`).
* Environment-driven configuration with zero hardcoded credentials:
  - `PORT`: HTTP port (default: `8080`).
  - `HOST`: Bind host (default: `0.0.0.0`).
  - `APP_ENV`: Runtime environment (`development`, `test`, `staging`, `production`).
  - `WORKER_CONCURRENCY`: Consumer pool worker count (default: `2`).
  - `MAX_ORCHESTRATION_CONCURRENCY`: DAG parallel execution bound per run (default: `4`).
  - `GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS`: Graceful drain period on SIGTERM (default: `30`).
  - `LOG_LEVEL` & `LOG_FORMAT`: Observability controls (`INFO`, `json`).

### 2.2 Containerization (`Dockerfile` & `.dockerignore`)
* Base: `python:3.12-slim` for minimal security footprint and small image size.
* Non-root user: `appuser` (UID 10001) for unprivileged runtime execution.
* Environment: `PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1`, `PYTHONPATH=/app/backend`.
* Layer caching: `pyproject.toml` dependencies cached in intermediate build layer.
* Excluded items in `.dockerignore`: `.git`, `.github`, test caches, virtual environments, `.env` files, doc drafts, and IDE metadata.
* Native Python healthcheck probe on `GET /healthz`.

### 2.3 Process Model Separation
1. **API Service (`backend/app/api/main.py`)**:
   - Executes FastAPI web gateway via `uvicorn app.api.app:create_app --factory`.
   - Exposes `/healthz`, `/openapi.json`, and `/api/v1/runs` endpoints.
2. **Worker Service (`backend/app/jobs/main.py`)**:
   - Standalone `StandaloneWorkerRunner` for decoupled background task processing.
   - Handles `SIGTERM` / `SIGINT` for graceful shutdown and in-flight job draining.

### 2.4 Local Orchestration (`docker-compose.yml`)
* Declarative multi-container configuration defining `api` and `worker` services.
* Environment variable bindings and healthcheck monitoring.

---

## 3. Cloud Deployment Topology (Google Cloud Platform)

| Component | GCP Service | Scaling / Topology |
| :--- | :--- | :--- |
| **Public Ingress** | Cloud Armor + Load Balancer | HTTPS termination, DDoS protection, WAF rules |
| **API Gateway** | Cloud Run (Service) | Autoscale 0-20 instances; executes `app.api.app:create_app` |
| **Worker Fleet** | Cloud Run (Worker Service / Job) | Autoscale 0-50 instances; executes `app.jobs.main` |
| **Job Queue** | Cloud Pub/Sub | Topic `researchmind-agent-tasks` with push/pull subscription |
| **Workflow State** | Cloud Firestore | ACID state snapshots, task trees, and distributed locks |
| **Vector DB** | Qdrant Cloud | Dense semantic embeddings retrieval for RAG |
| **Artifact Store** | Cloud Storage (GCS) | Immutable storage for generated `ResearchDossier` reports |
| **Secrets** | Cloud Secret Manager | Dynamic secret injection into Cloud Run environments |

---

## 4. In-Memory vs. Distributed Cloud Boundary

* **Phase 5.2 / Local Test**: Utilizes `InMemoryJobQueue` inside a single process or testing harness for deterministic synchronous/asynchronous test validation without external infrastructure.
* **Phase 5.3+ Distributed Production**: `JobPublisherProtocol` and `JobConsumerProtocol` act as clean dependency-injected interfaces, allowing seamless replacement with Cloud Pub/Sub clients without modifying agent algorithms, DAG execution, or security policies.
