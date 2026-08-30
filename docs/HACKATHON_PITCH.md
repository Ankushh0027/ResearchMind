# ResearchMind — Hackathon Pitch & Technical Talking Points

## 1. One-Line Pitch
**ResearchMind is an autonomous multi-agent research platform that transforms complex research questions into verifiable, evidence-grounded dossiers with contradiction detection and durable checkpoint recovery.**

---

## 2. 30-Second Elevator Pitch
> *"When asked deep research questions, traditional LLMs produce shallow answers, hallucinate citations, and overlook scientific disagreements. ResearchMind solves this by orchestrating a dynamic DAG of 6 specialized AI agents that decompose inquiries, ingest empirical literature from Gemini, Tavily, and arXiv, extract atomic claims, detect factual contradictions, and self-correct using automated quality rubrics. The result is a publication-ready research dossier with full evidence provenance."*

---

## 3. 60-Second Competition Pitch
> *"Every researcher, analyst, and engineer has experienced the frustration of asking an AI a complex scientific or technical question only to get back generic, ungrounded summaries with broken citations. 
> 
> ResearchMind moves beyond naive 'retrieve-and-generate' RAG. We built an autonomous multi-agent system where a Planner agent creates a structured investigation DAG; Researcher agents query academic papers and web sources; an Analyst agent extracts atomic factual assertions; a Verifier agent cross-examines claims and detects factual contradictions; and an Evaluator agent performs rubric scoring, triggering autonomous self-correction loops when needed.
> 
> Backed by enterprise infrastructure—Google Cloud Pub/Sub, Firestore checkpoints, worker lease recovery, OpenTelemetry tracing, and SHA-256 digest security—ResearchMind achieves a 0.9781 golden benchmark score across 849 automated tests. It turns hours of manual literature review into verified, actionable research intelligence in minutes."*

---

## 4. Problem Statement
- **Catastrophic Hallucinations**: Standard LLMs invent non-existent papers, statistics, and authors when prompted on specialized domains.
- **Surface-Level Synthesis**: Monolithic prompt chains fail to break multi-faceted problems into structured investigation paths.
- **Ignored Contradictions**: When research literature conflicts, naive models blend opposing perspectives into an ungrounded consensus rather than highlighting scientific debates.
- **Ephemeral State**: If a research job fails halfway through, all intermediate work is lost.

---

## 5. The Solution: ResearchMind
- **Specialized Multi-Agent Mesh**: `Planner`, `Researcher`, `Analyst`, `Verifier`, `Evaluator`, `Reporter`.
- **Atomic Claim Extraction**: Factual assertions are extracted as discrete units strictly bound to evidence record IDs.
- **Conflict & Divergence Analysis**: Contradictions are explicitly surfaced with severity ratings and conflicting claim IDs.
- **Autonomous Refinement Loop**: Self-correction triggers dynamic follow-up subtasks when coverage or citation thresholds are unmet.
- **Durable Checkpointing**: Intermediate state is saved to Cloud Firestore with automatic worker crash recovery.

---

## 6. Why Existing RAG Is Insufficient

| Dimension | Traditional RAG | ResearchMind Multi-Agent Architecture |
| :--- | :--- | :--- |
| **Pipeline Flow** | Query → Vector Search → Generate | Goal → Plan DAG → Multi-Source Search → Ingestion → Retrieval → Claim Synthesis → Cross-Verification → Self-Correction → Dossier |
| **Grounding** | Chunk concatenation in prompt | Atomic claim backlinks to exact source URLs and domain trust levels |
| **Contradictions** | Smooths over disagreements | Explicitly flags contradictions with divergence severity ratings |
| **Fault Tolerance** | Single failure aborts whole call | Worker leases & Firestore checkpoints resume from last subtask |
| **Evaluation** | None (best-effort) | Real-time rubric audit (Completeness, Citation Coverage, Unsupported Claim Rate) |

---

## 7. Technical Innovations
1. **Dependency-Aware DAG Scheduling**: Parallel subtask execution with cycle detection and dead-lock guards.
2. **Deterministic & LLM Hybrid Verification**: Rule-based claim proposition extraction paired with semantic cross-examination.
3. **Zero-Leakage Digest Auth**: Constant-time SHA-256 key hashing (`hmac.compare_digest`) with strict tenant IDOR isolation.
4. **Resilient SSE Streaming**: Browser client with bounded exponential backoff auto-reconnect and terminal state protection.

---

## 8. Reliability Architecture
- **Google Cloud Pub/Sub**: Asynchronous task distribution with Dead Letter Queues (DLQ).
- **Worker Lease Supervision**: Heartbeat renewals with automatic lease re-acquisition if an agent container crashes.
- **OpenTelemetry & Metrics**: W3C distributed trace propagation and structured JSON observability.

---

## 9. Benchmark Evidence
- **Golden Benchmark Composite Score**: **0.9781 / 1.0000** (Pass Threshold: 0.8500).
- **Test Suite**: **849 unit, integration, and E2E tests passing** across 229 source files.
- **Type Safety & Linting**: 100% strict Mypy and clean Ruff code formatting.

---

## 10. Future Scope
1. **Interactive Citation Graph Visualizer**: Interactive node-link graph mapping claim-evidence dependencies.
2. **Multi-Modal Evidence Ingestion**: Ingesting scientific charts, diagrams, and PDF figures via Gemini Multimodal.
3. **Enterprise Collaboration Portals**: Multi-user shared workspaces with fine-grained RBAC and team annotations.
