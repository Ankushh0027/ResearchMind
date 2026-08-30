# ResearchMind — Submission Assets & Media Checklist

## 1. Screenshot Checklist

Capture and include the following key screenshots for your submission gallery:

| Screenshot | Target View | What It Demonstrates |
| :--- | :--- | :--- |
| **01_hero_workspace.png** | Web Workspace Homepage (`http://localhost:8080/`) | Clean research workspace, suggestions, domain chips, and API health status badge. |
| **02_multi_agent_dag.png** | Multi-Agent Execution Pipeline (Active run) | Live state transitions (`Planner` → `Researcher` → `Analyst` → `Verifier` → `Evaluator` → `Reporter`). |
| **03_event_timeline.png** | Live Event Timeline & Diagnostics Console | Real-time SSE event stream, token usage counters (IN vs OUT), and subtask progress. |
| **04_executive_summary.png** | Dossier Tab: Executive Summary & Methodology | Comprehensive synthesized overview and search strategy breakdown. |
| **05_verified_claims.png** | Dossier Tab: Verified Claims & Citations | Atomic propositions linked to domain trust levels, confidence scores, and source URLs. |
| **06_contradictions.png** | Dossier Tab: Contradictions Detected | Explicit factual disagreement analysis between competing literature. |
| **07_evaluation_rubric.png** | Dossier Tab: Evaluation Report | Quality rubric scores (Completeness, Citation Coverage, Unsupported Claim Rate). |
| **08_artifact_explorer.png** | Artifact Explorer | Persistent deliverables (`.md` reports, `.json` dossiers) with SHA-256 integrity checksums. |
| **09_golden_benchmark.png** | CLI Terminal: `python -m app.cli.main benchmark` | Benchmark score **0.9781 / 1.0** across all 4 evaluation scenarios. |
| **10_github_ci_green.png** | GitHub Actions Workflow | All quality gates green (Pytest 849 tests, Ruff, Format, Mypy). |

---

## 2. Recommended 60–90 Second Demo Video Sequence

- **0:00 – 0:15 (The Hook)**:
  - Open on the ResearchMind dark-mode workspace.
  - State the core thesis: *"Single-turn AI chat produces ungrounded research. ResearchMind delivers autonomous, evidence-verified research dossiers."*
- **0:15 – 0:35 (Inquiry Launch & Live DAG)**:
  - Click the suggested RAG inquiry → Click **🚀 Start Investigation**.
  - Show the live multi-agent DAG pipeline transitioning across Planner, Researcher, Analyst, Verifier, Evaluator, and Reporter.
  - Highlight the live SSE event stream and token usage counter.
- **0:35 – 0:65 (The Dossier & Citations)**:
  - Show the compiled Executive Summary and Key Findings.
  - Click into **Verified Claims** to show direct provenance links back to source URLs.
  - Click into **Contradictions** to show explicit detection of conflicting scientific claims.
  - Show the **Evaluation Report** rubric metrics.
- **0:65 – 0:80 (Export & Architecture)**:
  - Click **Export .md** to demonstrate instant deliverable download.
  - Briefly flash the architecture diagram: *"Powered by Gemini, Qdrant, Pub/Sub, Firestore checkpoints, and worker lease auto-recovery."*
- **0:80 – 0:90 (Conclusion)**:
  - Show the CLI benchmark score: *"849 automated tests, 0.9781 golden benchmark score. ResearchMind turns days of research into verified intelligence in minutes."*
