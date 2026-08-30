# ResearchMind

> **Autonomous Asynchronous Multi-Agent Research System & Evidence Dossier Platform**

[![CI](https://github.com/Ankushh0027/ResearchMind/actions/workflows/ci.yml/badge.svg)](https://github.com/Ankushh0027/ResearchMind/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Type Checked: Mypy](https://img.shields.io/badge/type_checked-mypy-blue.svg)](https://mypy-lang.org/)
[![Benchmark Score](https://img.shields.io/badge/Golden%20Benchmark-0.9781%20%2F%201.0-emerald.svg)](#8-golden-benchmark-evaluation)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 1. What ResearchMind Is

**ResearchMind** is an enterprise-grade autonomous research platform powered by specialized multi-agent collaboration, deep retrieval-augmented generation (RAG), dynamic self-correction loops, and automated rubric evaluation. It transforms complex, open-ended research questions into comprehensive, citation-backed, conflict-checked investigative dossiers.

### The Problem It Solves
Standard single-turn LLM prompts suffer from **hallucinations, shallow synthesis, missing citations, and inability to handle contradicting sources**. When tasked with deep literature analysis or strategic research, single-turn LLMs smooth over nuanced scientific disagreements and cite non-existent papers.

### Why ResearchMind Is Different
1. **Dynamic Multi-Agent DAGs**: Breaks research goals into dependency-aware parallel subtasks across 6 specialized agent personas (`Planner`, `Researcher`, `Analyst`, `Verifier`, `Evaluator`, `Reporter`).
2. **Atomic Factual Claim Extraction & Grounding**: Claims are extracted as atomic propositions strictly linked to empirical evidence records.
3. **Contradiction Detection**: Explicitly identifies and documents factual disagreements between competing publications with divergence severity scores.
4. **Autonomous Self-Correction Loop**: The Evaluator agent scores completeness, citation coverage, and contradiction rates, dynamically kicking off inquiry refinement loops if acceptance thresholds are not met.
5. **Durable Enterprise Architecture**: Powered by Google Cloud Pub/Sub, Firestore checkpoints, worker lease supervisors with auto-recovery, OpenTelemetry distributed tracing, and constant-time SHA-256 API key authentication.

---

## 2. System Architecture

```mermaid
flowchart TD
    subgraph ClientTier [Client Tier]
        UI[Research Workspace Web UI\n(Vanilla HTML/CSS/ES Modules)]
        CLI[Operator CLI\n(researchmind)]
    end

    subgraph GatewayTier [Security Gateway]
        Gateway[FastAPI Gateway]
        Auth[SHA-256 Digest Auth & Tenant Isolation]
        RateLimit[Sliding-Window Rate Limiter]
        Headers[Security Headers & Anti-Caching]
    end

    subgraph TransportTier [Distributed Messaging & Recovery]
        PubSub[Google Cloud Pub/Sub]
        Supervisor[Worker Lease Supervisor & Heartbeat Reaper]
    end

    subgraph AgentMesh [Specialized Multi-Agent Mesh]
        Planner[1. Planner Agent] -->|DAG Tasks| PubSub
        Researcher[2. Researcher Agent] -->|Web & Academic Search| External[Tavily + arXiv + Gemini]
        Researcher -->|Chunks & Embeddings| Qdrant[(Qdrant Vector DB)]
        Qdrant -->|Context| Analyst[3. Analyst Agent]
        Analyst -->|Synthesized Claims| Verifier[4. Verifier Agent]
        Verifier -->|Conflict Detection| Evaluator[5. Evaluator Agent]
        Evaluator -.->|Refinement Loop Feedback| Researcher
        Evaluator -->|Approved Output| Reporter[6. Reporter Agent]
    end

    subgraph PersistenceTier [Persistence & Artifacts]
        Firestore[(Cloud Firestore Checkpoints)]
        GCS[(Cloud Storage GCS Deliverables)]
    end

    ClientTier --> GatewayTier --> TransportTier --> AgentMesh
    AgentMesh <--> PersistenceTier
```

---

## 3. Interactive Web Workspace (`frontend/`)

ResearchMind includes a responsive dark-mode Web Workspace:

```bash
# Start backend API and static web workspace
uvicorn app.api.app:create_app --factory --host 0.0.0.0 --port 8080 --reload

# Open in browser:
# http://localhost:8080/
```

### Key Workspace Capabilities
- **Inquiry Launchpad**: Research inquiry submission with domain chips, subtask limits, and suggestion prompts.
- **Live Multi-Agent Pipeline**: Real-time SSE execution visualization tracking `Planner` → `Researcher` → `Analyst` → `Verifier` → `Evaluator` → `Reporter`.
- **Live Event Timeline & Diagnostics**: Streaming event logs, token consumption counters (input vs output), subtask progress, and elapsed timers.
- **Research Dossier Studio**: Tabbed viewer for Executive Summaries, Key Findings, Grounded Claims, Contradiction Flags, and Evaluation Rubric metrics.
- **Artifact Explorer**: Verified persistent downloads (`.md` reports, `.json` dossiers) with SHA-256 checksum badges.

---

## 4. Operator CLI (`researchmind`)

```bash
# 1. Health Probe
researchmind health

# 2. Submit Autonomous Research Run
researchmind submit "Evaluate zero-noise extrapolation in quantum error mitigation." \
  --tags academic quantum \
  --max-subtasks 6

# 3. Stream Real-Time Execution Events (SSE)
researchmind stream <run_id>

# 4. Inspect Real-Time Status & Key Findings
researchmind status <run_id> --full

# 5. Export Deliverables to Disk
researchmind export <run_id> --output-dir ./artifacts

# 6. Execute Golden Evaluation Benchmark Suite
researchmind benchmark --threshold 0.85
```

---

## 5. Quickstart & Local Setup

### Installation
```bash
# Clone repository
git clone https://github.com/Ankushh0027/ResearchMind.git
cd ResearchMind

# Install package with all developer tools and CLI
pip install -e ".[dev]"
```

### Environment Configuration
```bash
# Copy template configuration
cp .env.example .env

# Edit .env to supply your Gemini API key (or run in deterministic mock mode)
export GEMINI_API_KEY="your_api_key_here"
```

---

## 6. Deterministic Demo & Smoke Testing

ResearchMind is designed to run in deterministic offline mock mode for instant evaluation:

```bash
# Run 9-point deployment smoke test suite
python scripts/smoke_test.py --mock

# Run automated golden evaluation benchmark suite (4/4 passed, 0.9781 composite score)
python -m app.cli.main benchmark
```

---

## 7. Full Quality Gate Verification

```bash
# 1. Run all 849 unit & integration tests
python -m pytest

# 2. Run Ruff linter and formatters
ruff check .
ruff format --check .

# 3. Run strict Mypy type-checking
mypy --python-version 3.12 backend/app backend/tests
```

---

## 8. Golden Benchmark Evaluation

ResearchMind is benchmarked across 4 complex multidisciplinary evaluation scenarios:

| Scenario | Domain | Quality Dimensions Evaluated | Score |
| :--- | :--- | :--- | :--- |
| **scenario_academic_quantum_01** | Quantum Computing | Grounding, Citation Precision, Coherence | **1.0000** |
| **scenario_biomedical_mrna_02** | Biomedical / mRNA | Contradiction Rate, Source Trust, Evidence Link | **1.0000** |
| **scenario_financial_cbdc_03** | Economics & Fintech | Completeness, Cross-Examination, Rubric | **1.0000** |
| **scenario_technical_rag_04** | AI & RAG Architecture | Synthesis Rigor, Unsupported Assertion Penalty | **0.9125** |
| **Composite Average** | **All Scenarios** | **Pass Threshold: 0.8500** | **0.9781 (PASS)** |

---

## 9. Verification Baseline Across Phases

- [x] **Phase 6.1**: Durable State & Checkpoint Persistence (Google Cloud Firestore)
- [x] **Phase 6.2**: Distributed Messaging & Task Distribution (Google Cloud Pub/Sub)
- [x] **Phase 6.3**: Live Gemini Intelligence Adapters & Structured Function Calling
- [x] **Phase 6.4**: Live Qdrant Vector Search + Tavily Web + arXiv Academic Integration
- [x] **Phase 6.5**: API Security, Sliding-Window Rate Limiting & SSRF Hardening
- [x] **Phase 6.6**: Durable Artifact Storage with Google Cloud Storage (GCS)
- [x] **Phase 6.7**: OpenTelemetry Distributed Tracing, Structured Metrics & Observability
- [x] **Phase 6.8**: Automated Evaluation Framework, Rubric Scoring & Golden Benchmark Suite
- [x] **Phase 6.9**: Autonomous Self-Correction, Dynamic Inquiry Refinement & Iterative Loop
- [x] **Phase 7.0**: Production Cloud Infrastructure, Operator CLI & Multi-Service Deployment Automation
- [x] **Phase 7.1**: Worker Leases, Heartbeat Supervision & Automatic Crash Recovery
- [x] **Phase 7.2**: Production API Security, SHA-256 Digest Auth & Tenant Isolation
- [x] **Phase 7.3**: Interactive Research Workspace & Live Multi-Agent Execution Studio
- [x] **Phase 7.4**: Production Browser Validation, Deployment Hardening & Product Polish
- [x] **Phase 7.5**: Hackathon Submission & Production Release Hardening
