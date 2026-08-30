# Devpost Submission Content: ResearchMind

## Project Title
**ResearchMind — Evidence-Grounded Multi-Agent Research System**

## Tagline
**Turn complex research questions into verifiable, evidence-backed research dossiers with autonomous multi-agent cross-examination.**

---

## Inspiration
When researching complex scientific, technical, or market questions, standard AI chat interfaces often fail in subtle, dangerous ways: they hallucinate citations, smooth over genuine disagreements in literature, and produce surface-level summaries without empirical grounding. 

We set out to build an autonomous research intelligence system that behaves like a team of specialized researchers: decomposing inquiries into structured investigation plans, searching primary academic and web literature, extracting atomic claims, detecting contradictions, and self-evaluating quality before compiling a comprehensive research dossier.

---

## What It Does
**ResearchMind** transforms open-ended research topics into publication-grade investigative dossiers:
- **Autonomous DAG Planning**: Decomposes inquiries into dependency-aware research subtasks.
- **Deep Evidence Ingestion**: Queries Google Gemini, Tavily Web Search, and arXiv Academic indexes, ingesting content into a Qdrant vector memory store.
- **Atomic Claim Extraction**: Distills factual propositions strictly tied to verified evidence records.
- **Contradiction Detection**: Explicitly identifies where literature or web sources disagree, calculating severity ratings.
- **Self-Correction & Refinement**: Evaluates research completeness and citation coverage against automated rubrics, triggering iterative refinement loops when needed.
- **Interactive Research Workspace**: A dark-mode web workspace streaming real-time execution events, token telemetry, interactive dossier tabs, and Markdown/JSON export with SHA-256 ETag verification.

---

## How We Built It
- **Intelligence Mesh**: Built with Python 3.12, orchestrating 6 specialized agent personas (`Planner`, `Researcher`, `Analyst`, `Verifier`, `Evaluator`, `Reporter`).
- **Distributed Transport**: Google Cloud Pub/Sub with Dead Letter Queues and background worker pools.
- **State & Checkpoints**: Google Cloud Firestore with worker lease heartbeats and automatic crash recovery.
- **Vector Search & RAG**: Qdrant vector database paired with Tavily Web and arXiv API integration.
- **API & Security**: FastAPI gateway featuring SHA-256 binary key digest authentication, multi-tenant IDOR isolation, sliding-window rate limiting, and SSRF guardrails.
- **Frontend Workspace**: Vanilla HTML5, CSS design tokens, and native ES modules with resilient Server-Sent Events (SSE) streaming and bounded backoff reconnection.

---

## Technical Architecture
```
User / Browser Workspace (SSE Stream)
     ↓
FastAPI Security Gateway (SHA-256 Digest Auth & Tenant Isolation)
     ↓
Google Cloud Pub/Sub Job Transport
     ↓
Worker Pool (Planner → Researcher → Analyst → Verifier → Evaluator → Reporter)
     ↓
Qdrant Vector DB + Gemini LLM + Tavily Web + arXiv Academic
     ↓
Google Cloud Firestore (Checkpoints) & Google Cloud Storage (Dossiers)
```

---

## Challenges We Overcame
1. **Preventing Claim Hallucination**: Implementing strict deterministic proposition extractors that enforce non-empty evidence backlinks before claims can enter the synthesis pipeline.
2. **Resilient SSE Streaming**: Building a zero-dependency SSE reader in native JavaScript that supports Bearer token authentication headers, bounded exponential backoff reconnection, and immutable terminal state guards.
3. **Worker Crash Recovery**: Developing a background lease supervisor that monitors worker heartbeats and automatically re-acquires uncompleted jobs from Firestore checkpoints.

---

## Accomplishments We're Proud Of
- **0.9781 Golden Benchmark Score**: Evaluated across 4 multidisciplinary scenarios (Quantum Computing, Biomedical mRNA, Fintech CBDCs, AI Architecture) exceeding the 0.8500 quality threshold.
- **849 Automated Tests Passing**: Exhaustive unit, integration, property, security, and browser E2E test coverage across 229 backend source files.
- **Zero-Dependency Modern Frontend**: Fast, responsive, dark-mode research workspace built entirely with vanilla web standards and CSS custom properties.
- **Turnkey Infrastructure**: Complete Infrastructure as Code using Terraform and automated Cloud Run deployment scripts.

---

## What We Learned
- Multi-agent collaboration works best with clear, single-responsibility agent personas and typed contract boundaries rather than monolithic prompt chaining.
- Explicit contradiction detection provides far higher research value than attempting to force artificial consensus across differing sources.

---

## What's Next for ResearchMind
- **Visual Citation Graphs**: Interactive node-link graph mapping claim-evidence provenance.
- **Multimodal Scientific Ingestion**: Extracting data from figures, charts, and tables in scientific papers using Gemini Multimodal.
- **Collaborative Research Portals**: Team workspaces with shared dossiers and annotation tools.

---

## Built With
- `python`
- `fastapi`
- `google-gemini`
- `qdrant`
- `google-cloud-pubsub`
- `google-cloud-firestore`
- `google-cloud-storage`
- `tavily`
- `arxiv`
- `opentelemetry`
- `terraform`
- `docker`
- `html5`
- `css3`
- `javascript`

---

## Try It Out
```bash
# 1. Clone and install
git clone https://github.com/Ankushh0027/ResearchMind.git
cd ResearchMind
pip install -e ".[dev]"

# 2. Run deterministic offline smoke test (9/9 checks)
python scripts/smoke_test.py --mock

# 3. Run golden evaluation benchmark suite (0.9781 composite score)
python -m app.cli.main benchmark

# 4. Start local Web Workspace
uvicorn app.api.app:create_app --factory --host 0.0.0.0 --port 8080 --reload
# Open http://localhost:8080/
```
