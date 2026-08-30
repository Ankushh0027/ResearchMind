# ResearchMind — 3-Minute Hackathon Demo Script & Judge Walkthrough

## Structure Overview (3:00 Minutes)

- **0:00 – 0:20**: Problem statement & 1-sentence value proposition
- **0:20 – 0:45**: Inquiry configuration & launch
- **0:45 – 1:30**: Live multi-agent DAG execution & event streaming
- **1:30 – 2:00**: Research Dossier (evidence, grounded claims, contradiction detection)
- **2:00 – 2:30**: Durable execution, lease supervision, and cooperative cancellation
- **2:30 – 3:00**: Technical differentiation & architecture recap

---

## Detailed Step-by-Step Script

### [0:00 – 0:20] The Problem & The Solution
- **Action**: Display the ResearchMind Web Workspace homepage (`http://localhost:8080/`).
- **Talking Point**:
  > *"When standard LLMs are asked complex, open-ended research questions, they produce shallow, ungrounded answers, hallucinate citations, and smooth over scientific disagreements. **ResearchMind** solves this with an autonomous multi-agent architecture that breaks inquiries into dependency DAGs, verifies claims against primary sources, detects factual contradictions, and compiles publication-grade research dossiers."*

---

### [0:20 – 0:45] Launching the Golden Demo Inquiry
- **Action**:
  1. Click the first pre-loaded suggestion chip:
     > *"Analyze the current state of retrieval-augmented generation for scientific research, identify the major reliability challenges, compare approaches, and provide evidence-backed conclusions."*
  2. Notice the domain tags: `ai, rag, scientific research, reliability`.
  3. Max Subtasks slider set to `10`.
  4. Click **🚀 Start Investigation**.
- **Talking Point**:
  > *"Rather than a single monolithic prompt, ResearchMind initiates a multi-stage investigation. The request is submitted to our FastAPI gateway with SHA-256 digest authentication and dispatched to our worker pool."*

---

### [0:45 – 1:30] Live Multi-Agent DAG Execution
- **Action**: Point to the **Multi-Agent Execution Pipeline** and **Live Event Timeline Console**.
- **Visuals to Highlight**:
  1. `Planner`: Decomposes the research topic into discrete subtasks.
  2. `Researcher`: Queries Tavily Web and arXiv academic indexes in parallel.
  3. `Analyst`: Extracts atomic factual propositions from vector chunks.
  4. `Verifier`: Cross-examines assertions against empirical evidence.
  5. `Evaluator`: Runs self-correction quality rubrics (completeness, citation coverage).
  6. `Reporter`: Synthesizes findings into the final Markdown and JSON deliverables.
  7. **Diagnostics Box**: Live token usage counter (input vs output), subtask progress, and elapsed execution timer.
- **Talking Point**:
  > *"All agent transitions and subtask progress are streamed in real time over Server-Sent Events with bounded backoff reconnection and zero polling latency."*

---

### [1:30 – 2:00] Exploring the Research Dossier & Evidence Provenance
- **Action**: Switch through the Dossier tabs:
  1. **Executive Summary & Methodology**: Clear analytical synthesis of findings.
  2. **Key Findings**: Grounded conclusions with individual confidence ratings (e.g. 95%).
  3. **Verified Claims**: Atomic facts linked directly to source domains and URLs.
  4. **Contradictions**: Disagreements between competing literature analyzed with severity ratings.
  5. **Evaluation Report**: Self-correction score across completeness, citation coverage, contradiction rate, and source diversity.
  6. **Evidence Sources**: Complete bibliography with trust levels (Peer-Reviewed, Official Doc, General Web).
- **Talking Point**:
  > *"Every single claim has direct traceability back to empirical sources. If two papers disagree, ResearchMind flags the contradiction instead of inventing a compromise."*

---

### [2:00 – 2:30] Reliability, Lease Supervision & Cancellation
- **Action**: Show the **⏹ Cancel Run** button and persistent artifact downloads.
- **Talking Point**:
  > *"Under the hood, worker leases in Google Cloud Pub/Sub and Cloud Firestore heartbeats protect against worker crashes. If an agent dies mid-execution, the lease supervisor detects the timeout and recovers from the last persistent checkpoint. Users can also cooperatively cancel runs at any point."*

---

### [2:30 – 3:00] Architecture Differentiation & Benchmark Results
- **Action**: Highlight the evaluation benchmark results:
  - **4/4 Scenarios Passed**
  - **0.9781 Composite Quality Score**
  - **849 Automated Unit & Integration Tests Passing**
- **Talking Point**:
  > *"Traditional RAG is just 'retrieve and generate'. ResearchMind is 'plan, decompose, search, cross-examine, verify, evaluate, and self-correct'. It is fully tested with 849 automated tests and a 0.9781 golden benchmark."*

---

## What NOT to Click During Demo
- Do NOT click "Clear Key" during an active run.
- Do NOT submit empty queries (handled with 422 validation, but keep demo focused on golden path).

## Fallback Plan (Offline Mock Mode)
If live external API rate limits or network issues occur:
```bash
# Run deterministic mock smoke test suite (9/9 checks passed)
python scripts/smoke_test.py --mock

# Run automated golden evaluation benchmark suite (4/4 passed, 0.9781 composite score)
python -m app.cli.main benchmark
```
