# Phase 7.0: Production Cloud Infrastructure, Operator CLI & Multi-Service Deployment Automation

---

## 1. Overview & Objective

Phase 7.0 delivers production deployment infrastructure, container topologies, and an interactive developer/operator Command Line Interface (`researchmind`) for the ResearchMind platform.

### Core Deliverables:
1. **Operator CLI (`backend/app/cli/`)**:
   - `researchmind health`: Liveness/readiness probe (`GET /healthz`).
   - `researchmind submit`: Submits research goals with domain tags and subtask bounds (`POST /api/v1/runs`).
   - `researchmind status`: Fetches execution state, metrics, key findings, and compiled dossiers (`GET /api/v1/runs/{id}`).
   - `researchmind stream`: Consumes real-time Server-Sent Events (SSE) detailing state transitions (`GET /api/v1/runs/{id}/events`).
   - `researchmind export`: Downloads durable artifacts directly to local disk (`GET /api/v1/runs/{id}/artifacts`).
   - `researchmind benchmark`: Runs offline golden benchmark evaluation with deterministic regression gate thresholds.
   - `researchmind cancel`: Signals cooperative cancellation (`POST /api/v1/runs/{id}/cancel`).
2. **Infrastructure as Code (`infrastructure/terraform/`)**:
   - Declarative GCP resources: Cloud Run v2 (API Gateway and Background Worker), Pub/Sub topics, subscriptions, and DLQ, Firestore in Native mode, Google Cloud Storage (GCS) artifacts bucket, and Secret Manager bindings with least-privilege IAM service accounts.
3. **Deployment Automation (`scripts/`)**:
   - `scripts/deploy.sh` & `scripts/deploy.ps1`: Fail-fast deployment automation scripts.
   - `scripts/smoke_test.py`: Multi-stage post-deployment smoke test suite with both live network and in-memory mock transport support.

---

## 2. Architecture & Service Topology

```text
Operator CLI / Web Client / CI Runner
                │
                ▼
      ┌───────────────────┐
      │  Cloud Run (API)  │ ◄─── Public / Load-Balanced Ingress (Port 8080)
      │  app.api.app      │
      └─────────┬─────────┘
                │
                ├─────────────────────────────┬─────────────────────────────┐
                ▼                             ▼                             ▼
   ┌──────────────────────────┐  ┌──────────────────────────┐  ┌──────────────────────────┐
   │    Cloud Firestore       │  │      Cloud Pub/Sub       │  │   Cloud Storage (GCS)    │
   │ (Runs, Tasks, State)     │  │ (researchmind-tasks)     │  │ (researchmind-artifacts) │
   └────────────┬─────────────┘  └────────────┬─────────────┘  └────────────┬─────────────┘
                │                             │                             │
                │                             ▼                             │
                │                ┌──────────────────────────┐               │
                └───────────────►│   Cloud Run (Worker)     │◄──────────────┘
                                 │   app.jobs.main          │
                                 └────────────┬─────────────┘
                                              │
                                              ├──────────────► Gemini 2.5 API
                                              ├──────────────► Qdrant Vector DB
                                              └──────────────► Academic / Web APIs
```

---

## 3. CLI Reference Guide

### Global Flags
| Flag | Environment Variable | Default | Description |
| :--- | :--- | :--- | :--- |
| `--url` | `RESEARCHMIND_API_URL` | `http://localhost:8080` | Target ResearchMind API Gateway base URL |
| `--api-key` | `RESEARCHMIND_API_KEY` | `None` | Authentication key for protected API endpoints |
| `--json` | - | `False` | Emit structured JSON output for programmatic pipelines |

### Subcommands

#### 1. `researchmind health`
Check system health and service liveness probe.
```bash
researchmind health
```

#### 2. `researchmind submit`
Submit an autonomous deep research inquiry.
```bash
researchmind submit "Evaluate zero-noise extrapolation in quantum error mitigation." \
  --tags academic quantum \
  --max-subtasks 6
```

#### 3. `researchmind status`
Retrieve research progress, token accounting, and synthesized findings.
```bash
researchmind status run_7faf73cdaae4 --full
```

#### 4. `researchmind stream`
Stream real-time multi-agent execution events via Server-Sent Events (SSE).
```bash
researchmind stream run_7faf73cdaae4
```

#### 5. `researchmind export`
Download research reports, dossiers, and evidence snapshots to a local folder.
```bash
researchmind export run_7faf73cdaae4 --output-dir ./artifacts
```

#### 6. `researchmind benchmark`
Execute the offline golden evaluation suite across 4 curated scientific/financial/technical domains.
```bash
researchmind benchmark --threshold 0.85
```

---

## 4. Verification & Quality Gates

| Gate | Status | Details |
| :--- | :--- | :--- |
| **Pytest Suite** | **PASS** | 811 tests passed in 10.14s (23 new CLI tests) |
| **Ruff Linter** | **PASS** | 0 errors |
| **Ruff Formatter** | **PASS** | 240 source files formatted |
| **Mypy Type Analysis** | **PASS** | 0 errors across 217 source files |
| **Smoke Test Suite** | **PASS** | 5/5 checks passed in mock transport mode |
| **Golden Benchmark CLI** | **PASS** | 4/4 scenarios passed (Average Score: 0.9781) |
