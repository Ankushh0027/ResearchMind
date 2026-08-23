"""Comprehensive unit tests for Phase 3.4.5 ReporterAgent and ResearchDossier."""

import pytest
from pydantic import ValidationError

from app.common.enums import SourceTrustLevel, VerificationStatus
from app.common.errors import EvidenceValidationError, ReportingError
from app.intelligence.analyst import AnalystAgent
from app.intelligence.claims import (
    DeterministicClaimExtractor,
    ExtractedClaim,
)
from app.intelligence.contradiction import ContradictionDetector
from app.intelligence.evaluator import EvaluatorAgent
from app.intelligence.evidence import EvidenceRecord, SourceProvenance
from app.intelligence.models import (
    CitationReference,
    ContradictionItem,
    KeyFinding,
    ResearchDossier,
)
from app.intelligence.reporter import (
    ReporterAgent,
    ReporterProtocol,
    generate_dossier_id,
)
from app.intelligence.verifier import VerifierAgent


def _make_sample_finding(run_id: str = "run_rep") -> KeyFinding:
    return KeyFinding(
        finding_id="fnd_01",
        run_id=run_id,
        title="Scalable Quantum Memory",
        narrative="Optical photon-to-matter interfaces achieve high fidelity quantum memory.",
        claim_ids=("clm_01",),
        evidence_ids=("ev_01",),
        confidence_score=0.95,
    )


def _make_sample_claim(run_id: str = "run_rep") -> ExtractedClaim:
    return ExtractedClaim(
        claim_id="clm_01",
        run_id=run_id,
        statement="Optical photon-to-matter interfaces achieve high fidelity quantum memory.",
        supporting_evidence_ids=("ev_01",),
        confidence_score=0.95,
    )


def _make_sample_citation(run_id: str = "run_rep") -> CitationReference:
    return CitationReference(
        citation_key="[CIT-01]",
        evidence_id="ev_01",
        source_url="https://nature.com/articles/quantum-memory",
        title="High Fidelity Quantum Memory",
        domain="nature.com",
        trust_level=SourceTrustLevel.PEER_REVIEWED,
        run_id=run_id,
    )


def test_reporter_protocol_compliance() -> None:
    """Verify ReporterAgent implements ReporterProtocol."""
    reporter = ReporterAgent()
    assert isinstance(reporter, ReporterProtocol)


@pytest.mark.asyncio
async def test_valid_research_dossier_compilation() -> None:
    """Verify compilation of a publication-grade ResearchDossier with complete sections."""
    reporter = ReporterAgent()
    finding = _make_sample_finding()
    claim = _make_sample_claim()
    citation = _make_sample_citation()

    dossier: ResearchDossier = await reporter.compile_dossier(
        goal_query="How do optical photon-to-matter interfaces scale in quantum networks?",
        findings=[finding],
        claims=[claim],
        citations=[citation],
        contradictions=[],
        run_id="run_rep",
    )

    assert dossier.run_id == "run_rep"
    assert dossier.confidence_rating == 0.95
    assert dossier.verification_status == VerificationStatus.VERIFIED
    assert len(dossier.key_findings) == 1
    assert len(dossier.claims) == 1
    assert len(dossier.citations) == 1
    assert "# Research Dossier:" in dossier.markdown_report
    assert "## Executive Summary" in dossier.markdown_report
    assert "## Comprehensive Bibliography & Sources" in dossier.markdown_report
    assert "[CIT-01]" in dossier.markdown_report


@pytest.mark.asyncio
async def test_empty_goal_query_rejection() -> None:
    """Verify empty goal_query raises ReportingError."""
    reporter = ReporterAgent()
    with pytest.raises(ReportingError) as exc_info:
        await reporter.compile_dossier(
            goal_query="   ",
            findings=[],
            claims=[],
            citations=[],
            contradictions=[],
            run_id="run_01",
        )
    assert exc_info.value.code == "EMPTY_GOAL"


@pytest.mark.asyncio
async def test_strict_run_id_isolation() -> None:
    """Verify reporter rejects items belonging to mismatched run IDs."""
    reporter = ReporterAgent()
    finding_foreign = _make_sample_finding(run_id="run_FOREIGN")

    with pytest.raises(EvidenceValidationError) as exc_info:
        await reporter.compile_dossier(
            goal_query="Quantum Networks",
            findings=[finding_foreign],
            claims=[],
            citations=[],
            contradictions=[],
            run_id="run_rep",
        )
    assert "does not match" in str(exc_info.value)


@pytest.mark.asyncio
async def test_contradictions_and_evaluation_rendering_in_dossier() -> None:
    """Verify contradictions and evaluation results are rendered cleanly in markdown."""
    reporter = ReporterAgent()
    finding = _make_sample_finding()
    claim = _make_sample_claim()
    citation = _make_sample_citation()
    contradiction = ContradictionItem(
        item_id="cnt_01",
        run_id="run_rep",
        description="Factual disagreement on decoherence rates",
        conflicting_claim_ids=("clm_01", "clm_02"),
        divergence_analysis="Competing empirical measurements",
        severity_score=0.85,
    )

    evaluator = EvaluatorAgent()
    evaluation = await evaluator.evaluate_research(
        goal_query="Quantum Networks",
        findings=[finding],
        claims=[claim],
        citations=[citation],
        contradictions=[contradiction],
        run_id="run_rep",
    )

    dossier = await reporter.compile_dossier(
        goal_query="Quantum Networks",
        findings=[finding],
        claims=[claim],
        citations=[citation],
        contradictions=[contradiction],
        run_id="run_rep",
        evaluation=evaluation,
    )

    assert dossier.verification_status == VerificationStatus.CONTRADICTED
    assert (
        "## Documented Contradictions & Divergent Perspectives"
        in dossier.markdown_report
    )
    assert "## Quality Audit & Self-Evaluation" in dossier.markdown_report
    assert "Conflict: cnt_01" in dossier.markdown_report


def test_immutable_dossier_and_extra_fields_rejection() -> None:
    """Verify ResearchDossier is frozen and rejects unauthorized extra fields."""
    dossier = ResearchDossier(
        dossier_id="dos_01",
        run_id="run_01",
        goal_query="Goal",
        methodology_summary="Methodology",
        executive_summary="Exec",
        confidence_rating=0.90,
        markdown_report="# Markdown",
    )
    with pytest.raises(ValidationError):
        dossier.confidence_rating = 0.50

    with pytest.raises(ValidationError):
        ResearchDossier(
            dossier_id="dos_01",
            run_id="run_01",
            goal_query="Goal",
            methodology_summary="Methodology",
            executive_summary="Exec",
            confidence_rating=0.90,
            markdown_report="# Markdown",
            unauthorized_key="injected",  # type: ignore[call-arg]
        )


@pytest.mark.asyncio
async def test_full_end_to_end_intelligence_pipeline_lifecycle() -> None:
    """Test full Phase 3.4 lifecycle integration: Evidence -> Claims -> Findings -> Contradictions -> Verification -> Evaluation -> ResearchDossier."""
    run_id = "run_full_e2e_3_4"
    goal_query = "Assess mRNA vaccine mechanisms and delivery via lipid nanoparticles."

    # 1. Evidence
    ev1 = EvidenceRecord.create(
        evidence_id="ev_mrna_01",
        run_id=run_id,
        normalized_content="mRNA vaccines utilize lipid nanoparticles to protect genetic sequences during delivery.",
        provenance=SourceProvenance.from_content(
            raw_content="mRNA vaccines utilize lipid nanoparticles to protect genetic sequences during delivery.",
            title="mRNA Nanoparticle Delivery",
            source_url="https://nature.com/articles/mrna-lnp",
            trust_level=SourceTrustLevel.PEER_REVIEWED,
        ),
    )
    ev2 = EvidenceRecord.create(
        evidence_id="ev_mrna_02",
        run_id=run_id,
        normalized_content="Nanoparticle encapsulation improves cellular uptake and translation efficiency.",
        provenance=SourceProvenance.from_content(
            raw_content="Nanoparticle encapsulation improves cellular uptake and translation efficiency.",
            title="Cellular Translation Efficiency",
            source_url="https://science.org/doi/10.1126/mrna-trans",
            trust_level=SourceTrustLevel.PEER_REVIEWED,
        ),
    )

    # 2. Claim Extraction
    extractor = DeterministicClaimExtractor()
    extracted_claims_res = await extractor.extract_claims([ev1, ev2], run_id=run_id)
    assert extracted_claims_res.total_claims == 2
    claims = list(extracted_claims_res.claims)

    # 3. Analyst Finding Synthesis
    analyst = AnalystAgent()
    analysis_res = await analyst.analyze_claims(
        claims, run_id=run_id, research_goal=goal_query
    )
    assert analysis_res.total_findings >= 1
    findings = list(analysis_res.findings)

    # 4. Contradiction Detection
    contradiction_detector = ContradictionDetector()
    cnt_res = await contradiction_detector.detect_contradictions(claims, run_id=run_id)
    assert cnt_res.has_contradictions is False
    contradictions = list(cnt_res.contradictions)

    # 5. Grounding Verification & Citation Mapping
    verifier = VerifierAgent()
    ver_res = await verifier.verify_claims(
        claims, [ev1, ev2], run_id=run_id, contradictions=contradictions
    )
    assert ver_res.overall_status == VerificationStatus.VERIFIED
    assert len(ver_res.citations) == 2
    citations = list(ver_res.citations)

    # 6. Evaluation & Quality Audit
    evaluator = EvaluatorAgent()
    eval_res = await evaluator.evaluate_research(
        goal_query=goal_query,
        findings=findings,
        claims=claims,
        citations=citations,
        contradictions=contradictions,
        run_id=run_id,
    )
    assert eval_res.passed is True

    # 7. Final Research Dossier Compilation
    reporter = ReporterAgent()
    dossier = await reporter.compile_dossier(
        goal_query=goal_query,
        findings=findings,
        claims=claims,
        citations=citations,
        contradictions=contradictions,
        run_id=run_id,
        evaluation=eval_res,
    )

    assert dossier.run_id == run_id
    assert dossier.verification_status == VerificationStatus.VERIFIED
    assert dossier.confidence_rating >= 0.70
    assert len(dossier.key_findings) >= 1
    assert len(dossier.claims) == 2
    assert len(dossier.citations) == 2
    assert "[CIT-01]" in dossier.markdown_report
    assert "[CIT-02]" in dossier.markdown_report
    assert "## Quality Audit & Self-Evaluation" in dossier.markdown_report


def test_generate_dossier_id_utility() -> None:
    """Verify generate_dossier_id generates unique prefixed identifiers."""
    d1 = generate_dossier_id()
    d2 = generate_dossier_id()
    assert d1 != d2
    assert d1.startswith("dos_")
