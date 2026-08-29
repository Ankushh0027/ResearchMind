"""Unit tests for the automated evaluation framework, rubric scoring engine, and claim matcher."""

from app.common.enums import VerificationStatus
from app.evaluation.dataset import (
    GOLDEN_BENCHMARK_SUITE,
    SCENARIO_QUANTUM_ERROR_MITIGATION,
    SCENARIO_TECHNICAL_RAG_VS_LONG_CONTEXT,
    get_scenario_by_id,
)
from app.evaluation.harness import evaluate_dossier
from app.evaluation.models import (
    GroundTruthFact,
)
from app.evaluation.rubrics import (
    GROUNDEDNESS_WEIGHT,
    NEUTRALITY_WEIGHT,
    SCOPE_WEIGHT,
    calculate_citation_metrics,
    calculate_composite_score,
    calculate_groundedness,
    calculate_neutrality,
    calculate_scope,
    compute_token_overlap,
    match_claim,
    normalize_text,
    tokenize,
)
from app.intelligence.models import (
    CitationReference,
    ContradictionItem,
    KeyFinding,
    ResearchDossier,
)


def _make_dummy_dossier(
    findings: list[KeyFinding] | None = None,
    citations: list[CitationReference] | None = None,
    contradictions: list[ContradictionItem] | None = None,
    summary: str = "Test executive summary",
    markdown: str = "Test markdown report content",
) -> ResearchDossier:
    return ResearchDossier(
        dossier_id="dossier_test_01",
        run_id="run_test_01",
        goal_query="Test research question",
        methodology_summary="Subtask query decomposition strategy",
        executive_summary=summary,
        key_findings=tuple(findings or []),
        citations=tuple(citations or []),
        contradictions=tuple(contradictions or []),
        confidence_rating=0.90,
        verification_status=VerificationStatus.VERIFIED,
        markdown_report=markdown,
    )


class TestRubricWeightings:
    """Validate rubric mathematical definitions and normalization constraints."""

    def test_rubric_weights_sum_to_one(self) -> None:
        total = GROUNDEDNESS_WEIGHT + SCOPE_WEIGHT + NEUTRALITY_WEIGHT
        assert abs(total - 1.0) < 1e-9

    def test_exact_rubric_weight_values(self) -> None:
        assert GROUNDEDNESS_WEIGHT == 0.40
        assert SCOPE_WEIGHT == 0.35
        assert NEUTRALITY_WEIGHT == 0.25

    def test_composite_score_bounds(self) -> None:
        assert calculate_composite_score(1.0, 1.0, 1.0) == 1.0
        assert calculate_composite_score(0.0, 0.0, 0.0) == 0.0
        assert calculate_composite_score(-0.5, 0.0, 0.0) == 0.0
        assert calculate_composite_score(1.5, 1.0, 1.0) == 1.0

    def test_composite_score_formula_exactness(self) -> None:
        groundedness = 0.80
        scope = 0.90
        neutrality = 0.70
        expected = (
            0.40 * 0.80 + 0.35 * 0.90 + 0.25 * 0.70
        )  # 0.32 + 0.315 + 0.175 = 0.81
        actual = calculate_composite_score(groundedness, scope, neutrality)
        assert abs(actual - expected) < 1e-6


class TestTextNormalizationAndMatching:
    """Test deterministic tokenization, normalization, and claim matching."""

    def test_normalize_text_punctuation_and_case(self) -> None:
        raw = "  Zero-Noise Extrapolation, with P-values < 0.05!! "
        norm = normalize_text(raw)
        assert norm == "zeronoise extrapolation with pvalues 005"

    def test_tokenize_filters_stopwords(self) -> None:
        tokens = tokenize(
            "This is a comprehensive study on the quantum error mitigations."
        )
        assert "this" not in tokens
        assert "is" not in tokens
        assert "the" not in tokens
        assert "quantum" in tokens
        assert "error" in tokens
        assert "mitigations" in tokens

    def test_compute_token_overlap(self) -> None:
        text_a = "quantum error mitigation superconducting qubits"
        text_b = "superconducting qubits quantum processors"
        overlap = compute_token_overlap(text_a, text_b)
        assert 0.40 <= overlap <= 0.70

        assert compute_token_overlap("hello world", "unrelated topic") == 0.0
        assert compute_token_overlap("identical sentence", "identical sentence") == 1.0

    def test_match_claim_exact_and_partial(self) -> None:
        fact = GroundTruthFact(
            fact_id="f1",
            claim="Zero-noise extrapolation scales without physical qubit overhead.",
            normalized_claim="zero-noise extrapolation scales without physical qubit overhead",
            is_required=True,
            keywords=("zero-noise", "overhead", "extrapolation"),
        )

        exact_match = "We found that zero-noise extrapolation scales without physical qubit overhead effectively."
        assert match_claim(exact_match, fact) == 1.0

        partial_match = "Zero-noise extrapolation methods avoid physical qubit overhead during execution."
        score = match_claim(partial_match, fact)
        assert score >= 0.50

        unrelated = (
            "Classical machine learning methods perform stochastic gradient descent."
        )
        assert match_claim(unrelated, fact) == 0.0


class TestGroundednessScoring:
    """Test groundedness calculations across complete, partial, and empty dossiers."""

    def test_empty_dossier_scores_zero(self) -> None:
        dossier = _make_dummy_dossier(findings=[])
        scenario = SCENARIO_QUANTUM_ERROR_MITIGATION
        score, feedback = calculate_groundedness(dossier, scenario)
        assert score == 0.0
        assert len(feedback) > 0
        assert "contains no key findings" in feedback[0]

    def test_fully_grounded_dossier(self) -> None:
        findings = [
            KeyFinding(
                finding_id="kf_1",
                title="ZNE Scaling",
                narrative="Zero-noise extrapolation scales error mitigation without physical qubit overhead by pulse amplification.",
            ),
            KeyFinding(
                finding_id="kf_2",
                title="PEC Sampling Overhead",
                narrative="Probabilistic error cancellation requires exponential sampling overhead as circuit depth grows.",
            ),
            KeyFinding(
                finding_id="kf_3",
                title="Surface Code Thresholds",
                narrative="Surface codes require physical-to-logical qubit ratios exceeding 1000:1 for fault-tolerant error thresholds.",
            ),
        ]
        dossier = _make_dummy_dossier(findings=findings)
        score, feedback = calculate_groundedness(
            dossier, SCENARIO_QUANTUM_ERROR_MITIGATION
        )
        assert score >= 0.90
        assert len(feedback) == 0

    def test_partially_grounded_dossier(self) -> None:
        findings = [
            KeyFinding(
                finding_id="kf_1",
                title="ZNE Scaling",
                narrative="Zero-noise extrapolation scales error mitigation without physical qubit overhead.",
            ),
        ]
        dossier = _make_dummy_dossier(findings=findings)
        score, feedback = calculate_groundedness(
            dossier, SCENARIO_QUANTUM_ERROR_MITIGATION
        )
        assert 0.20 <= score <= 0.50
        assert len(feedback) > 0


class TestScopeScoring:
    """Test required and optional topic completeness evaluation."""

    def test_full_topic_coverage(self) -> None:
        scenario = SCENARIO_TECHNICAL_RAG_VS_LONG_CONTEXT
        markdown = """
        # Comparative Analysis
        ## Hybrid Dense Sparse RAG
        Combines dense embeddings with BM25.
        ## Monolithic Long-Context LLMs
        Analyzes time to first token TTFT latency and compute inference economics.
        """
        dossier = _make_dummy_dossier(
            markdown=markdown,
            summary="Comprehensive analysis of hybrid RAG and long-context LLMs.",
        )
        score, feedback = calculate_scope(dossier, scenario)
        assert score == 1.0
        assert len(feedback) == 0

    def test_missing_required_topics(self) -> None:
        scenario = SCENARIO_TECHNICAL_RAG_VS_LONG_CONTEXT
        dossier = _make_dummy_dossier(markdown="Only talks about basic keyword search.")
        score, feedback = calculate_scope(dossier, scenario)
        assert score < 0.50
        assert len(feedback) > 0
        assert "Omitted required subtopics" in feedback[0]


class TestNeutralityScoring:
    """Test contradiction precision, recall, and neutrality rating."""

    def test_neutrality_with_expected_contradictions_matched(self) -> None:
        scenario = SCENARIO_QUANTUM_ERROR_MITIGATION
        contra = ContradictionItem(
            item_id="c1",
            description="Conflicting circuit depth scalability in Zero-Noise Extrapolation.",
            conflicting_claim_ids=("c_a", "c_b"),
            divergence_analysis="One source shows stability up to 100 gate depths while another reports failure beyond 30 gate depths.",
        )
        dossier = _make_dummy_dossier(contradictions=[contra])
        score, prec, rec, feedback = calculate_neutrality(dossier, scenario)
        assert rec == 1.0
        assert prec == 1.0
        assert score == 1.0
        assert len(feedback) == 0

    def test_neutrality_missing_contradictions(self) -> None:
        scenario = SCENARIO_QUANTUM_ERROR_MITIGATION
        dossier = _make_dummy_dossier(contradictions=[])
        score, prec, rec, feedback = calculate_neutrality(dossier, scenario)
        assert score == 0.0
        assert rec == 0.0
        assert len(feedback) > 0


class TestCitationMetrics:
    """Test citation precision and recall calculations."""

    def test_citation_metrics_full_match(self) -> None:
        scenario = SCENARIO_QUANTUM_ERROR_MITIGATION
        citations = [
            CitationReference(
                citation_key="[CIT-01]",
                evidence_id="ev1",
                source_url="https://arxiv.org/abs/quantum-zne-benchmark",
                title="ZNE Benchmark",
                domain="arxiv.org",
            ),
            CitationReference(
                citation_key="[CIT-02]",
                evidence_id="ev2",
                source_url="https://arxiv.org/abs/pec-sampling-overhead",
                title="PEC Overhead",
                domain="arxiv.org",
            ),
            CitationReference(
                citation_key="[CIT-03]",
                evidence_id="ev3",
                source_url="https://arxiv.org/abs/surface-code-thresholds",
                title="Surface Codes",
                domain="arxiv.org",
            ),
        ]
        dossier = _make_dummy_dossier(citations=citations)
        prec, rec, feedback = calculate_citation_metrics(dossier, scenario)
        assert prec == 1.0
        assert rec == 1.0
        assert len(feedback) == 0

    def test_citation_metrics_empty_dossier(self) -> None:
        scenario = SCENARIO_QUANTUM_ERROR_MITIGATION
        dossier = _make_dummy_dossier(citations=[])
        prec, rec, feedback = calculate_citation_metrics(dossier, scenario)
        assert prec == 0.0
        assert rec == 0.0
        assert "contains no citations" in feedback[0]


class TestGoldenDatasetAndHarness:
    """Validate dataset structure and single dossier evaluation."""

    def test_golden_dataset_structure(self) -> None:
        assert len(GOLDEN_BENCHMARK_SUITE) >= 4
        domains = {s.domain for s in GOLDEN_BENCHMARK_SUITE}
        assert "academic" in domains
        assert "biomedical" in domains
        assert "financial" in domains
        assert "technical" in domains

        for s in GOLDEN_BENCHMARK_SUITE:
            assert len(s.required_topics) >= 2
            assert len(s.ground_truth_facts) >= 2
            assert len(s.expected_citations) >= 1
            assert s.minimum_quality_threshold >= 0.80

    def test_get_scenario_by_id(self) -> None:
        s = get_scenario_by_id("scenario_academic_quantum_01")
        assert s is not None
        assert s.domain == "academic"

        assert get_scenario_by_id("non_existent_scenario") is None

    def test_evaluate_dossier_passing(self) -> None:
        scenario = SCENARIO_QUANTUM_ERROR_MITIGATION
        findings = [
            KeyFinding(
                finding_id="kf_1",
                title="Zero-Noise Extrapolation",
                narrative="Zero-noise extrapolation scales error mitigation without physical qubit overhead by amplifying pulse noise and extrapolating to zero limit.",
            ),
            KeyFinding(
                finding_id="kf_2",
                title="Probabilistic Error Cancellation",
                narrative="Probabilistic error cancellation requires exponential sampling overhead as circuit depth grows.",
            ),
            KeyFinding(
                finding_id="kf_3",
                title="Surface Code Overhead",
                narrative="Surface codes require physical-to-logical qubit ratios exceeding 1000:1 for fault-tolerant error thresholds.",
            ),
        ]
        citations = [
            CitationReference(
                citation_key="[CIT-01]",
                evidence_id="ev1",
                source_url="https://arxiv.org/abs/quantum-zne-benchmark",
                title="Quantum ZNE Benchmark",
                domain="arxiv.org",
            ),
            CitationReference(
                citation_key="[CIT-02]",
                evidence_id="ev2",
                source_url="https://arxiv.org/abs/pec-sampling-overhead",
                title="PEC Sampling",
                domain="arxiv.org",
            ),
            CitationReference(
                citation_key="[CIT-03]",
                evidence_id="ev3",
                source_url="https://arxiv.org/abs/surface-code-thresholds",
                title="Surface Codes",
                domain="arxiv.org",
            ),
        ]
        contra = ContradictionItem(
            item_id="c1",
            description="Disagreement on zero-noise extrapolation depth bounds.",
            conflicting_claim_ids=("c_a", "c_b"),
            divergence_analysis="One study claims stability up to 100 gate depths, whereas another reports failure beyond 30 gate depths.",
        )
        markdown = """
        # Quantum Error Mitigation vs Fault-Tolerant Surface Codes
        Analyzing zero-noise extrapolation, probabilistic error cancellation, fault-tolerant surface codes, and decoherence physical qubit overhead.
        """
        dossier = _make_dummy_dossier(
            findings=findings,
            citations=citations,
            contradictions=[contra],
            summary="Thorough analysis of zero-noise extrapolation, probabilistic error cancellation, and surface codes.",
            markdown=markdown,
        )

        result = evaluate_dossier(dossier, scenario)
        assert result.passed is True
        assert result.composite_score >= 0.85
        assert result.groundedness_score >= 0.85
        assert result.scope_score == 1.0
        assert result.neutrality_score == 1.0

    def test_evaluate_dossier_failing_with_actionable_feedback(self) -> None:
        scenario = SCENARIO_QUANTUM_ERROR_MITIGATION
        # Completely degraded dossier
        dossier = _make_dummy_dossier(
            findings=[],
            citations=[],
            contradictions=[],
            summary="Vague overview with no technical substance.",
            markdown="# Incomplete Draft\nNo technical details.",
        )
        result = evaluate_dossier(dossier, scenario)
        assert result.passed is False
        assert result.composite_score < 0.30
        assert len(result.actionable_feedback) >= 3
        # Ensure diagnostic feedback messages are present
        joined = " ".join(result.actionable_feedback)
        assert "fell below scenario threshold" in joined
        assert "no key findings" in joined

    def test_duplicate_citations_precision(self) -> None:
        scenario = SCENARIO_QUANTUM_ERROR_MITIGATION
        citations = [
            CitationReference(
                citation_key="[CIT-01]",
                evidence_id="ev1",
                source_url="https://arxiv.org/abs/quantum-zne-benchmark",
                title="Quantum ZNE Benchmark",
                domain="arxiv.org",
            ),
            CitationReference(
                citation_key="[CIT-02]",
                evidence_id="ev2",
                source_url="https://arxiv.org/abs/quantum-zne-benchmark",  # duplicate URL
                title="Quantum ZNE Benchmark",
                domain="arxiv.org",
            ),
            CitationReference(
                citation_key="[CIT-03]",
                evidence_id="ev3",
                source_url="https://arxiv.org/abs/quantum-zne-benchmark",  # duplicate URL
                title="Quantum ZNE Benchmark",
                domain="arxiv.org",
            ),
        ]
        dossier = _make_dummy_dossier(citations=citations)
        prec, rec, feedback = calculate_citation_metrics(dossier, scenario)
        assert rec <= 0.40  # only 1 of 3 expected citations matched
        assert prec <= 0.40  # 1 matched expected out of 3 citations

    def test_run_benchmark_with_missing_dossier(self) -> None:
        from app.evaluation.harness import run_benchmark

        scorecard = run_benchmark(dossiers={}, scenarios=GOLDEN_BENCHMARK_SUITE)
        assert scorecard.total_scenarios == len(GOLDEN_BENCHMARK_SUITE)
        assert scorecard.passed_scenarios == 0
        assert scorecard.failed_scenarios == len(GOLDEN_BENCHMARK_SUITE)
        assert scorecard.average_composite_score == 0.0
        assert scorecard.regression_gate_passed is False
