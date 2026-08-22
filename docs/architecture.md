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
  │  (Publishes tasks to Google Cloud Pub/Sub)
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

### 2.2 Taskmaster / Orchestrator
- Coordinates the execution lifecycle across agent stages.
- Manages dependencies between subtasks using a Directed Acyclic Graph (DAG).
- Enforces execution timeouts, concurrency limits, and retry policies.
- Handles worker heartbeat monitoring and failure recovery.

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

### 3.1 Persistent State
All workflow state mutations are committed atomically to **Google Cloud Firestore**. Every task execution produces a state snapshot containing:
- Run ID & Task ID
- Current stage & timestamp
- Input parameters & execution context
- Evidence gathered & agent decisions
- Checkpoint tokens allowing safe resumption

### 3.2 Idempotency
- Every subtask is assigned a deterministic hash based on its run ID, subtask key, and input parameters.
- If a message is redelivered by Pub/Sub (at-least-once delivery), the worker checks Firestore before executing. If the task state is already completed, the duplicate is acknowledged and skipped.

### 3.3 Retries & Exponential Backoff
- Transient failures (e.g., API rate limits, network timeouts) trigger automatic retries with exponential backoff and jitter.
- Non-retryable errors (e.g., policy violations, malformed inputs) immediately transition the specific subtask to a `FAILED` state while allowing independent branches to continue.

### 3.4 Failure Recovery
- State machines are designed to be crash-resilient.
- If an agent worker crashes during execution, the orchestrator detects missing heartbeats and reassigns the uncompleted subtask to a fresh worker instance using the last committed checkpoint in Firestore.

---

## 4. Observability & Telemetry

- **Structured JSON Logging**: All logs are emitted in structured JSON format with correlated `trace_id`, `run_id`, and `agent_id` fields compatible with Google Cloud Logging.
- **Trace Context Propagation**: Distributed trace headers propagate across Pub/Sub messages and agent boundaries.
- **Metrics & Auditing**: Detailed operational metrics (token usage, latency per agent, verification rejection rates) are recorded for continuous evaluation.

---

## 5. Security & Isolation Boundaries

- **Least Privilege Access**: Agent workers operate under scoped GCP Service Accounts with minimal IAM permissions.
- **Data Isolation**: Each research session maintains strict multi-tenant data boundaries in both Firestore and Qdrant.
- **Prompt Injection Defense**: All external content ingested by Research Agents (web pages, PDFs) is treated as untrusted data and strictly sanitized before being fed into reasoning prompts.
- **No Secret Persistence**: API keys and infrastructure credentials are exclusively injected via Cloud Secret Manager or environment variables at runtime.
