# ResearchMind — Production System Architecture

## 1. System Overview

ResearchMind is an enterprise-grade autonomous research platform designed for distributed, multi-agent investigation, deep evidence synthesis, and citation-backed report generation.

```mermaid
flowchart TD
    subgraph ClientLayer [Client & Interface Tier]
        WebUI[Research Workspace Web UI\n(Vanilla HTML/CSS/ES Modules)]
        CLI[Operator CLI\n(researchmind)]
        SDK[API Clients & Webhooks]
    end

    subgraph SecurityGateway [Security & API Gateway Tier]
        Gateway[FastAPI REST Gateway]
        AuthGuard[SHA-256 Digest Auth & Tenant Isolation]
        RateLimiter[Sliding-Window Rate Limiter]
        Headers[Security Headers & Anti-Caching]
        SizeGuard[ASGI Payload Size Guard]
        TraceMid[W3C OpenTelemetry Trace Context]
    end

    subgraph JobTransport [Distributed Transport & Worker Tier]
        PubSubQueue[Google Cloud Pub/Sub\n(Dead Letter Queue + Ack Leases)]
        Supervisor[Worker Lease Supervisor\n(Heartbeat Reaper & Auto-Recovery)]
        WorkerPool[Autonomous Agent Worker Pool]
    end

    subgraph AgentMesh [Specialized Multi-Agent Mesh]
        Planner[1. Planner Agent\n(Inquiry Decomposition)]
        Researcher[2. Researcher Agent\n(Web & Academic Ingestion)]
        Analyst[3. Analyst Agent\n(Atomic Claim Extraction)]
        Verifier[4. Verifier Agent\n(Contradiction & Grounding)]
        Evaluator[5. Evaluator Agent\n(Quality Rubric & Refinement)]
        Reporter[6. Reporter Agent\n(Dossier Compilation)]
    end

    subgraph ExternalAdapters [External Intelligence & Search Adapters]
        Gemini[Google Gemini 2.5/3.7 Pro & Flash]
        Tavily[Tavily Web Search]
        Arxiv[arXiv Academic Integration]
        SSRF[SSRF Security Firewall & IP Validator]
    end

    subgraph PersistenceLayer [State, Vector & Artifact Storage]
        Firestore[(Google Cloud Firestore\nCheckpoints & Run State)]
        Qdrant[(Qdrant Vector DB\nContext Embeddings)]
        GCS[(Google Cloud Storage\nMarkdown & JSON Dossiers)]
    end

    ClientLayer --> SecurityGateway
    SecurityGateway --> JobTransport
    JobTransport --> AgentMesh
    AgentMesh <--> ExternalAdapters
    AgentMesh <--> PersistenceLayer
```

---

## 2. Tier Architecture

### Tier 1: Client & Interface Tier
- **Web Workspace (`frontend/`)**: Native ES modules, responsive CSS design tokens, real-time SSE stream reader, and tabbed dossier explorer.
- **Operator CLI (`researchmind`)**: Command-line interface for operators and automated CI/CD benchmark evaluations.

### Tier 2: Security & API Gateway Tier
- **Constant-Time Digest Auth**: SHA-256 binary key hashing via `hmac.compare_digest` with zero plaintext secret retention.
- **Multi-Tenant Isolation**: Request context binds directly to `tenant_id`; cross-tenant access returns HTTP 404 to prevent resource enumeration.
- **Defense in Depth**: Sliding-window rate limiting (60 req/min), ASGI request size guards (1 MiB max), SSRF blocking for loopback/link-local IPs.

### Tier 3: Distributed Transport & Worker Tier
- **Message Transport**: Google Cloud Pub/Sub with configurable topic/subscription pairs and Dead Letter Queues (DLQ).
- **Lease Supervision**: Heartbeat renewals with automatic lease re-acquisition and checkpoint recovery on worker crashes.

### Tier 4: Multi-Agent Intelligence Mesh
- **Decomposition**: `Planner` builds dynamic subtask dependency DAGs.
- **Ingestion & RAG**: `Researcher` queries Tavily/arXiv, sanitizes untrusted input, and stores chunks in Qdrant.
- **Claim Synthesis**: `Analyst` extracts atomic factual assertions.
- **Cross-Examination**: `Verifier` cross-checks claims and detects conflicting assertions.
- **Self-Correction**: `Evaluator` evaluates coverage and triggers autonomous refinement loops if thresholds aren't met.
- **Compilation**: `Reporter` formats publication-grade Markdown and JSON dossiers.

### Tier 5: Persistence & Storage Tier
- **Cloud Firestore**: Structured run state, subtask statuses, and execution checkpoints.
- **Cloud Storage (GCS)**: Deliverables stored with SHA-256 ETag integrity verification.
- **Qdrant**: Vector index for semantic retrieval.
