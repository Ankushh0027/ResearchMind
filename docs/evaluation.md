# Evaluation & Quality Assurance Framework

This document defines the evaluation criteria, scoring rubrics, and automated benchmarking methodology for ResearchMind.

---

## 1. Multi-Dimensional Evaluation Rubric

ResearchMind assesses synthesized research quality along three primary axes:

### 1.1 Groundedness & Factual Faithfulness (Weight: 40%)
- Measures whether every claim in the report is strictly supported by collected evidence.
- Evaluates citation accuracy (does citation `[1]` support statement `X`?).
- Penalizes unsupported extrapolations and ungrounded speculation.

### 1.2 Inquiry Scope & Completeness (Weight: 35%)
- Compares the final report against the original user research goal and the Planner's subtasks.
- Checks whether all critical questions and sub-domains were explored or omitted.

### 1.3 Contradiction Detection & Neutrality (Weight: 25%)
- Checks whether conflicting claims between different primary sources were identified and explained rather than averaged away.
- Evaluates objectivity and balanced presentation of competing viewpoints.

---

## 2. Automated Self-Evaluation Loop

```
Draft Report Findings
         │
         ▼
Evaluator Agent (LLM-as-a-Judge)
         │
         ├── Score >= 0.85 ──► Proceed to Reporter Agent
         │
         └── Score < 0.85  ──► Formulate feedback & dispatch targeted subtasks
                               to Researcher Agent (Max 2 refinement loops)
```

---

## 3. Offline Benchmark Suite

- **Golden Query Dataset**: A curated set of complex, multi-hop research questions with human-annotated ground truth facts.
- **Automated Regression Testing**: Continuous integration runs evaluate candidate agent prompt changes against the golden benchmark suite to catch regression in synthesis quality.
