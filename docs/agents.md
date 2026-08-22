# Agent Contracts & Interfaces

This document formalizes the operational responsibilities, expected input schemas, and output contracts for each autonomous agent in ResearchMind.

---

## 1. Planner Agent

### Responsibility
Decomposes high-level research questions into targeted subtasks, formulates search strategies, and builds a dependency execution graph.

### Contract
- **Input**:
  ```json
  {
    "run_id": "run_12345",
    "research_goal": "Investigate the trade-offs of using hybrid RAG architectures vs monolithic long-context models in financial analysis",
    "constraints": {
      "max_subtasks": 5,
      "domains_allowed": ["academic", "technical", "industry"],
      "depth": "deep"
    }
  }
  ```
- **Output**:
  ```json
  {
    "plan_id": "plan_98765",
    "subtasks": [
      {
        "subtask_id": "task_01",
        "description": "Analyze retrieval latency and compute cost trade-offs in hybrid RAG",
        "search_queries": ["hybrid RAG retrieval latency cost", "vector DB vs long context LLM compute cost"],
        "dependencies": []
      },
      {
        "subtask_id": "task_02",
        "description": "Evaluate hallucination rates in monolithic long-context LLMs for financial tables",
        "search_queries": ["long context LLM needle in a haystack financial tabular data hallucination"],
        "dependencies": []
      }
    ]
  }
  ```

---

## 2. Researcher Agent

### Responsibility
Executes individual research subtasks by querying search tools, scraping primary documents, extracting direct quotes, and storing evidence records.

### Contract
- **Input**:
  ```json
  {
    "run_id": "run_12345",
    "subtask_id": "task_01",
    "objective": "Analyze retrieval latency and compute cost trade-offs in hybrid RAG",
    "queries": ["hybrid RAG retrieval latency cost"]
  }
  ```
- **Output**:
  ```json
  {
    "subtask_id": "task_01",
    "evidence_records": [
      {
        "evidence_id": "ev_001",
        "source_url": "https://example.org/paper-on-rag-cost",
        "title": "Empirical Analysis of Hybrid RAG Systems",
        "snippet": "Hybrid RAG reduces per-query token cost by 68% compared to full-context ingestion for documents exceeding 100k tokens.",
        "authors": ["A. Smith", "B. Doe"],
        "publication_date": "2025-11-10",
        "credibility_score": 0.92
      }
    ]
  }
  ```

---

## 3. Analyst Agent

### Responsibility
Synthesizes evidence collected across multiple subtasks, clusters related points, detects emergent themes, and formulates structured claims.

### Contract
- **Input**:
  ```json
  {
    "run_id": "run_12345",
    "evidence_records": [
      {
        "evidence_id": "ev_001",
        "source_url": "https://example.org/paper-on-rag-cost",
        "snippet": "Hybrid RAG reduces per-query token cost by 68% compared to full-context ingestion..."
      }
    ]
  }
  ```
- **Output**:
  ```json
  {
    "findings": [
      {
        "finding_id": "f_101",
        "claim": "Hybrid RAG delivers significant cost efficiency for large corpora compared to monolithic context windows.",
        "supporting_evidence_ids": ["ev_001"],
        "summary": "Economic analysis shows a 68% token reduction on large documents.",
        "potential_contradictions": []
      }
    ]
  }
  ```

---

## 4. Verifier Agent

### Responsibility
Cross-references every finding against primary source evidence, identifies contradicting claims, and assigns verification confidence ratings.

### Contract
- **Input**:
  ```json
  {
    "run_id": "run_12345",
    "findings": [
      {
        "finding_id": "f_101",
        "claim": "Hybrid RAG delivers significant cost efficiency for large corpora compared to monolithic context windows.",
        "supporting_evidence_ids": ["ev_001"]
      }
    ],
    "evidence_pool": [
      {
        "evidence_id": "ev_001",
        "snippet": "Hybrid RAG reduces per-query token cost by 68%..."
      }
    ]
  }
  ```
- **Output**:
  ```json
  {
    "verification_results": [
      {
        "finding_id": "f_101",
        "status": "VERIFIED",
        "confidence": 0.95,
        "citation_mapping": [
          {
            "evidence_id": "ev_001",
            "citation_label": "[1]",
            "grounding_check": "PASS"
          }
        ],
        "conflicts_detected": []
      }
    ]
  }
  ```

---

## 5. Evaluator Agent

### Responsibility
Performs meta-evaluation and self-critique on the draft synthesis, ensuring comprehensive coverage of the original goal, logical coherence, and absence of bias.

### Contract
- **Input**:
  ```json
  {
    "run_id": "run_12345",
    "original_goal": "Investigate the trade-offs of using hybrid RAG architectures vs monolithic long-context models in financial analysis",
    "draft_findings": [
      {
        "finding_id": "f_101",
        "claim": "Hybrid RAG delivers significant cost efficiency..."
      }
    ]
  }
  ```
- **Output**:
  ```json
  {
    "evaluation_id": "eval_555",
    "passed": true,
    "quality_score": 0.89,
    "rubric_breakdown": {
      "groundedness": 0.95,
      "goal_coverage": 0.88,
      "contradiction_resolution": 0.85
    },
    "feedback": "Sufficient evidence and grounding achieved. Ready for reporting."
  }
  ```

---

## 6. Reporter Agent

### Responsibility
Compiles verified findings, citations, and evaluation metadata into cohesive, publication-grade research dossiers formatted in Markdown and structured JSON.

### Contract
- **Input**:
  ```json
  {
    "run_id": "run_12345",
    "research_goal": "Investigate the trade-offs of using hybrid RAG architectures vs monolithic long-context models in financial analysis",
    "verified_findings": [
      {
        "finding_id": "f_101",
        "claim": "Hybrid RAG delivers significant cost efficiency...",
        "citations": ["[1]"]
      }
    ],
    "bibliography": [
      {
        "citation_label": "[1]",
        "source_url": "https://example.org/paper-on-rag-cost",
        "title": "Empirical Analysis of Hybrid RAG Systems"
      }
    ]
  }
  ```
- **Output**:
  ```json
  {
    "report_id": "rep_999",
    "artifact_url": "gs://researchmind-artifacts-dev/reports/run_12345/final_report.md",
    "executive_summary": "Comprehensive comparative assessment of Hybrid RAG vs Long-Context LLMs...",
    "markdown_content": "# Research Dossier: Hybrid RAG vs Long-Context LLMs\n\n## Executive Summary\n...",
    "generated_at": "2026-08-22T12:00:00Z"
  }
  ```
