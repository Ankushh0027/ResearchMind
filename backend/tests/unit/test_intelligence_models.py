"""Unit tests for ResearchDossier, EvaluationReport, and intelligence schemas."""

import pytest
from pydantic import ValidationError

from app.common.enums import SourceTrustLevel, VerificationStatus
from app.common.evidence import ExtractedClaim
from app.intelligence.models import (
    CitationReference,
    ContradictionItem,
    EvaluationReport,
    EvaluationRubricScore,
    KeyFinding,
    ResearchDossier,
)


def _make_sample_claim() -> ExtractedClaim:
    return ExtractedClaim(
        claim_id="claim_01",
        run_id="run_01",
        statement="Distributed state machines enable zero-downtime recovery.",
        supporting_evidence_ids=("ev_01", "ev_02"),
        confidence_score=0.95,
    )


def _make_sample_citation() -> CitationReference:
    return CitationReference(
        citation_key="[CIT-01]",
        evidence_id="ev_01",
        source_url="https://arxiv.org/abs/2401.99999",
        title="Reliable Multi-Agent Systems",
        domain="arxiv.org",
        trust_level=SourceTrustLevel.PEER_REVIEWED,
    )


def _make_sample_evaluation() -> EvaluationReport:
    rubric = EvaluationRubricScore(
        rubric_name="citation_grounding",
        score=0.95,
        weight=1.5,
        feedback="All claims are backed by peer-reviewed evidence.",
    )
    return EvaluationReport(
        report_id="eval_rep_01",
        run_id="run_01",
        plan_id="plan_01",
        passed=True,
        overall_score=0.92,
        completeness_score=0.90,
        citation_coverage_score=0.98,
        contradiction_rate=0.0,
        unsupported_claim_rate=0.0,
        source_diversity_score=0.85,
        rubric_scores=(rubric,),
        summary_critique="Rigorous and comprehensive analysis.",
    )


def test_research_dossier_creation_and_serialization() -> None:
    """Verify ResearchDossier instantiates, serializes, and deserializes cleanly."""
    claim = _make_sample_claim()
    citation = _make_sample_citation()
    evaluation = _make_sample_evaluation()

    finding = KeyFinding(
        finding_id="find_01",
        title="Fault Tolerance Invariants",
        narrative="FSM transitions guarantee state consistency.",
        claim_ids=("claim_01",),
        evidence_ids=("ev_01",),
    )

    dossier = ResearchDossier(
        dossier_id="dossier_01",
        run_id="run_01",
        goal_query="How to achieve resilient multi-agent orchestration?",
        methodology_summary="Topological DAG execution with cryptographic checkpointing.",
        executive_summary="Orchestration state machines prevent orphaned tasks.",
        key_findings=(finding,),
        claims=(claim,),
        citations=(citation,),
        contradictions=(),
        limitations=("Network partition testing was simulated.",),
        confidence_rating=0.94,
        verification_status=VerificationStatus.VERIFIED,
        evaluation=evaluation,
        markdown_report="# Executive Report\n\nVerified findings...",
    )

    # Immutability
    with pytest.raises(ValidationError):
        dossier.confidence_rating = 0.5

    # Serialization roundtrip
    json_str = dossier.model_dump_json()
    reloaded = ResearchDossier.model_validate_json(json_str)

    assert reloaded.dossier_id == "dossier_01"
    assert len(reloaded.key_findings) == 1
    assert reloaded.key_findings[0].title == "Fault Tolerance Invariants"
    assert reloaded.evaluation is not None
    assert reloaded.evaluation.overall_score == 0.92


def test_contradiction_item_validation() -> None:
    """Verify ContradictionItem requires at least two conflicting claim IDs."""
    with pytest.raises(ValidationError):
        ContradictionItem(
            item_id="contra_01",
            description="Speed of light dispute",
            conflicting_claim_ids=("claim_only_one",),  # Violates min_length=2
            divergence_analysis="One source claims faster-than-light neutrinos.",
        )

    valid_item = ContradictionItem(
        item_id="contra_01",
        description="Speed of light dispute",
        conflicting_claim_ids=("claim_01", "claim_02"),
        divergence_analysis="Experimental measurement discrepancy.",
    )
    assert len(valid_item.conflicting_claim_ids) == 2


def test_evaluation_report_score_bounds() -> None:
    """Verify EvaluationReport rejects scores outside [0.0, 1.0]."""
    with pytest.raises(ValidationError):
        EvaluationReport(
            report_id="eval_01",
            run_id="run_01",
            plan_id="plan_01",
            passed=True,
            overall_score=1.5,  # Invalid: > 1.0
            completeness_score=0.9,
            citation_coverage_score=0.9,
            contradiction_rate=0.0,
            unsupported_claim_rate=0.0,
            source_diversity_score=0.8,
            summary_critique="Score too high.",
        )


def test_extra_fields_forbidden_on_models() -> None:
    """Verify extra attributes are strictly rejected."""
    with pytest.raises(ValidationError):
        KeyFinding(
            finding_id="find_01",
            title="Title",
            narrative="Narrative",
            unauthorized_field="malicious_injection",  # type: ignore[call-arg]
        )
