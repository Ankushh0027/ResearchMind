"""Comprehensive unit tests for Phase 3.4.5 EvaluatorAgent and EvaluationReport."""

import pytest
from pydantic import ValidationError

from app.common.enums import SourceTrustLevel
from app.common.errors import EvaluationError, EvidenceValidationError
from app.intelligence.claims import ExtractedClaim
from app.intelligence.evaluator import (
    EvaluatorAgent,
    EvaluatorProtocol,
    generate_eval_id,
)
from app.intelligence.models import (
    CitationReference,
    ContradictionItem,
    EvaluationReport,
    KeyFinding,
)


def _make_sample_finding(run_id: str = "run_eval") -> KeyFinding:
    return KeyFinding(
        finding_id="fnd_01",
        run_id=run_id,
        title="Superconducting Qubit Scalability",
        narrative="Superconducting circuits provide scalable quantum computation with low latency.",
        claim_ids=("clm_01",),
        evidence_ids=("ev_01",),
        confidence_score=0.95,
    )


def _make_sample_claim(run_id: str = "run_eval") -> ExtractedClaim:
    return ExtractedClaim(
        claim_id="clm_01",
        run_id=run_id,
        statement="Superconducting circuits provide scalable quantum computation.",
        supporting_evidence_ids=("ev_01",),
        confidence_score=0.95,
    )


def _make_sample_citation(run_id: str = "run_eval") -> CitationReference:
    return CitationReference(
        citation_key="[CIT-01]",
        evidence_id="ev_01",
        source_url="https://nature.com/articles/qubit",
        title="Qubit Scaling",
        domain="nature.com",
        trust_level=SourceTrustLevel.PEER_REVIEWED,
        run_id=run_id,
    )


def test_evaluator_protocol_compliance() -> None:
    """Verify EvaluatorAgent implements EvaluatorProtocol."""
    evaluator = EvaluatorAgent()
    assert isinstance(evaluator, EvaluatorProtocol)


@pytest.mark.asyncio
async def test_valid_evaluation_report_generation() -> None:
    """Verify comprehensive self-evaluation produces a passing EvaluationReport with full metrics."""
    evaluator = EvaluatorAgent(pass_threshold=0.70)
    finding = _make_sample_finding()
    claim = _make_sample_claim()
    citation = _make_sample_citation()

    report: EvaluationReport = await evaluator.evaluate_research(
        goal_query="Investigate superconducting qubit scalability in quantum computing",
        findings=[finding],
        claims=[claim],
        citations=[citation],
        contradictions=[],
        run_id="run_eval",
        plan_id="plan_quantum",
    )

    assert report.run_id == "run_eval"
    assert report.plan_id == "plan_quantum"
    assert report.passed is True
    assert report.overall_score >= 0.70
    assert report.citation_coverage_score == 1.0
    assert report.contradiction_rate == 0.0
    assert report.unsupported_claim_rate == 0.0
    assert report.source_diversity_score > 0.0
    assert len(report.rubric_scores) == 4
    assert "PASSED" in report.summary_critique


@pytest.mark.asyncio
async def test_empty_goal_query_rejection() -> None:
    """Verify empty or whitespace goal_query raises EvaluationError."""
    evaluator = EvaluatorAgent()
    with pytest.raises(EvaluationError) as exc_info:
        await evaluator.evaluate_research(
            goal_query="   ",
            findings=[],
            claims=[],
            citations=[],
            contradictions=[],
            run_id="run_01",
        )
    assert exc_info.value.code == "EMPTY_GOAL_QUERY"


@pytest.mark.asyncio
async def test_strict_run_id_isolation() -> None:
    """Verify evaluation rejects items belonging to a mismatched run_id."""
    evaluator = EvaluatorAgent()
    finding_foreign = _make_sample_finding(run_id="run_OTHER")

    with pytest.raises(EvidenceValidationError) as exc_info:
        await evaluator.evaluate_research(
            goal_query="Quantum computing research",
            findings=[finding_foreign],
            claims=[],
            citations=[],
            contradictions=[],
            run_id="run_eval",
        )
    assert "does not match" in str(exc_info.value)


@pytest.mark.asyncio
async def test_failing_evaluation_on_zero_citations_and_findings() -> None:
    """Verify evaluation fails when findings or citations are lacking."""
    evaluator = EvaluatorAgent(pass_threshold=0.70)
    claim = _make_sample_claim()

    report = await evaluator.evaluate_research(
        goal_query="Investigate qubit scalability",
        findings=[],
        claims=[claim],
        citations=[],
        contradictions=[],
        run_id="run_eval",
    )

    assert report.passed is False
    assert report.completeness_score == 0.0
    assert report.citation_coverage_score == 0.0
    assert report.unsupported_claim_rate == 1.0
    assert "FAILED" in report.summary_critique


@pytest.mark.asyncio
async def test_contradiction_rate_impact_on_score() -> None:
    """Verify contradictions appropriately elevate contradiction_rate."""
    evaluator = EvaluatorAgent()
    finding = _make_sample_finding()
    claim = _make_sample_claim()
    citation = _make_sample_citation()
    contradiction = ContradictionItem(
        item_id="cnt_01",
        run_id="run_eval",
        description="Conflicting scalability metrics",
        conflicting_claim_ids=("clm_01", "clm_02"),
        divergence_analysis="Divergent lab results",
    )

    report = await evaluator.evaluate_research(
        goal_query="Qubit scalability",
        findings=[finding],
        claims=[claim],
        citations=[citation],
        contradictions=[contradiction],
        run_id="run_eval",
    )

    assert report.contradiction_rate == 1.0


def test_immutable_report_and_extra_fields_rejection() -> None:
    """Verify EvaluationReport is frozen and rejects unauthorized extra fields."""
    report = EvaluationReport(
        report_id="eval_01",
        run_id="run_01",
        passed=True,
        overall_score=0.85,
        completeness_score=0.90,
        citation_coverage_score=0.85,
        contradiction_rate=0.0,
        unsupported_claim_rate=0.15,
        source_diversity_score=0.75,
        summary_critique="Passed audit.",
    )
    with pytest.raises(ValidationError):
        report.overall_score = 0.99

    with pytest.raises(ValidationError):
        EvaluationReport(
            report_id="eval_01",
            run_id="run_01",
            passed=True,
            overall_score=0.85,
            completeness_score=0.90,
            citation_coverage_score=0.85,
            contradiction_rate=0.0,
            unsupported_claim_rate=0.15,
            source_diversity_score=0.75,
            summary_critique="Passed audit.",
            injected_field="illegal",  # type: ignore[call-arg]
        )


def test_generate_eval_id_utility() -> None:
    """Verify generate_eval_id generates distinct prefixed identifiers."""
    e1 = generate_eval_id()
    e2 = generate_eval_id()
    assert e1 != e2
    assert e1.startswith("eval_")
