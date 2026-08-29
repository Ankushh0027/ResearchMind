# Phase 6.8 — Automated Evaluation Framework, Rubric Scoring & Golden Benchmark Suite

Phase 6.8 delivers a deterministic, offline quality assurance and automated evaluation subsystem for ResearchMind. It allows continuous regression testing of synthesized research deliverables (`ResearchDossier`, `KeyFinding`, `CitationReference`, `ContradictionItem`) against curated gold-standard benchmark scenarios across academic, biomedical, financial, and technical domains.

---

## 1. Architecture Overview

```
+-----------------------------------------------------------------------------------+
|                        Golden Benchmark Scenario                                  |
|   - Research Question & Inquiry Goals                                            |
|   - Required Inquiry Topics                                                      |
|   - Canonical Ground Truth Facts & Citation Sources                               |
|   - Expected Contradiction Pairs                                                  |
+-----------------------------------------------------------------------------------+
                                        |
                 [1] Passed to Deterministic Evaluation Harness
                                        v
+-----------------------------------------------------------------------------------+
|                          ResearchDossier (Candidate)                              |
|   - Key Findings & Narratives                                                     |
|   - Citation Index & Provenance                                                   |
|   - Documented Contradiction Items                                                |
|   - Executive Summary & Formatted Markdown Deliverable                            |
+-----------------------------------------------------------------------------------+
                                        |
                 [2] Multi-Dimensional Rubric Engine Scoring
                                        v
                    +---------------------------------------+
                    |             Rubric Engine             |
                    |   1. Groundedness (Weight: 40%)       |
                    |   2. Scope Completeness (Weight: 35%) |
                    |   3. Neutrality / Conflict (25%)      |
                    +---------------------------------------+
                                        |
                 [3] Citation Metrics & Diagnostic Feedback
                                        v
                    +---------------------------------------+
                    |           BenchmarkResult             |
                    |   - Composite Score [0.0 - 1.0]       |
                    |   - Threshold Pass/Fail (>= 0.85)     |
                    |   - Itemized Diagnostic Deductions    |
                    +---------------------------------------+
                                        |
                 [4] Benchmark Aggregation & Regression Gate
                                        v
                    +---------------------------------------+
                    |         EvaluationScorecard           |
                    |   - Suite-wide Average Scores         |
                    |   - Regression Gate: Pass/Fail        |
                    +---------------------------------------+
```

---

## 2. Formal Multi-Dimensional Rubric Engine (`app.evaluation.rubrics`)

The composite quality score is computed using the weighted formula specified in [`docs/evaluation.md`](file:///c:/Users/Ankush/Desktop/ResearchMind/docs/evaluation.md):

$$\text{Composite Score} = 0.40 \times \text{Groundedness} + 0.35 \times \text{Scope} + 0.25 \times \text{Neutrality}$$

Every score is bounded within $[0.0, 1.0]$.

### 2.1 Groundedness & Factual Faithfulness (Weight: 40%)
- Compares finding narratives and executive summaries in `ResearchDossier` against expected canonical `GroundTruthFact` items.
- Utilizes deterministic token overlap ($Jaccard$), inclusion coefficients, and salient keyword matching.
- Penalizes empty findings, unsupported extrapolations, or ungrounded assertions.

### 2.2 Inquiry Scope & Completeness (Weight: 35%)
- Evaluates analytical coverage of scenario `required_topics`.
- Checks presence of required subtopics across the synthesis, methodology, and report markdown.
- `optional_topics` provide depth context without artificially penalizing completeness scores.

### 2.3 Contradiction Detection & Neutrality (Weight: 25%)
- Evaluates whether expected factual divergences between primary sources were captured in `dossier.contradictions`.
- Calculates contradiction recall ($\frac{\text{matched expected pairs}}{\text{total expected pairs}}$) and precision ($\frac{\text{matched expected pairs}}{\text{total dossier contradictions}}$).
- Rewards balanced, objective presentation over naive averaging.

### 2.4 Citation Precision & Recall
- **Citation Precision**: $\frac{\text{valid cited references}}{\text{total citations cited}}$
- **Citation Recall**: $\frac{\text{required ground truth citations represented}}{\text{required citations}}$
- Explicitly handles zero-denominator edge cases (e.g. scenarios expecting zero citations return $1.0$).

---

## 3. Deterministic Claim Matching & Text Normalization

To ensure 100% network independence and sub-second CI execution, claim matching avoids runtime LLMs or remote embedding APIs in favor of deterministic normalization:
1. **Punctuation & Case Normalization**: Strips ASCII punctuation, standardizes casing, and collapses whitespace.
2. **Stopword Filtering**: Removes common English grammatical particles (`the`, `is`, `with`, `for`, etc.).
3. **Token Overlap ($Jaccard$)**: Computes $\frac{|A \cap B|}{|A \cup B|}$ for symmetric phrase similarity.
4. **Token Inclusion Coefficient**: Computes $\frac{|A \cap B|}{|A|}$ to match short factual claims embedded within larger analytical paragraphs.
5. **Keyword Salience**: Boosts match confidence when designated domain keywords appear.

---

## 4. Curated Golden Benchmark Dataset (`app.evaluation.dataset`)

The benchmark suite includes four multi-hop scenarios across key inquiry domains:

| Scenario ID | Domain | Research Topic | Required Subtopics | Expected Citations | Contradictions |
|---|---|---|---|---|---|
| `scenario_academic_quantum_01` | Academic | Quantum Error Mitigation (ZNE & PEC) vs Surface Codes | 4 | 3 | 1 |
| `scenario_biomedical_mrna_02` | Biomedical | Lipid Nanoparticle (LNP) mRNA vs AAV Vectors | 4 | 2 | 1 |
| `scenario_financial_cbdc_03` | Financial | Wholesale CBDC vs Fiat-Backed Stablecoins | 4 | 2 | 1 |
| `scenario_technical_rag_04` | Technical | Hybrid Dense-Sparse RAG vs Monolithic Long-Context LLMs | 4 | 2 | 1 |

---

## 5. Evaluation Harness & Regression Gate (`app.evaluation.harness`)

- **`evaluate_dossier(dossier, scenario) -> BenchmarkResult`**: Evaluates a candidate dossier against a specific benchmark scenario.
- **`run_benchmark(dossiers, scenarios, minimum_threshold=0.85) -> EvaluationScorecard`**: Evaluates the full suite, computes aggregate metrics, and checks the regression gate ($\text{regression\_gate\_passed} = \text{True}$ iff all scenarios achieve $\ge 0.85$).
- **Telemetry Integration**: Emits `evaluation.runs_total`, `evaluation.duration_ms`, and `evaluation.score` metrics via `app.observability.metrics` when available (fail-safe).

---

## 6. Determinism & Performance Guarantees

1. **Sub-second Execution**: The full benchmark suite executes in $< 0.1\text{s}$ locally and in CI.
2. **Deterministic Output**: Zero random seeds, zero timestamps in scoring logic, and zero network calls ensure identical scorecards on repeated runs.
3. **Fail-Safe Operation**: Telemetry recording is wrapped with exception suppression, preventing observability failures from failing benchmark runs.

---

## 7. Known Limitations

- The claim matching algorithm is a **deterministic heuristic**, designed for regression testing and CI verification against structured ground-truth facts. It is not an open-domain semantic reasoning engine.
