"""Comprehensive unit tests for Phase 3.4.2 AnalystAgent and Thematic Analysis."""

import pytest
from pydantic import ValidationError

from app.common.enums import SourceTrustLevel
from app.common.errors import (
    AnalysisError,
    EvidenceValidationError,
)
from app.intelligence.analyst import (
    AnalystAgent,
    AnalystProtocol,
    ThematicAnalysisResult,
    generate_finding_id,
)
from app.intelligence.claims import (
    DeterministicClaimExtractor,
    ExtractedClaim,
)
from app.intelligence.evidence import EvidenceRecord, SourceProvenance
from app.intelligence.models import KeyFinding


def _make_claim(
    statement: str,
    evidence_ids: tuple[str, ...] = ("ev_01",),
    claim_id: str = "clm_01",
    run_id: str = "run_01",
    confidence_score: float = 0.90,
    topic_tags: tuple[str, ...] = ("Quantum",),
    is_untrusted: bool = False,
    is_quarantined: bool = False,
    source_domain: str = "nature.com",
) -> ExtractedClaim:
    return ExtractedClaim(
        claim_id=claim_id,
        run_id=run_id,
        statement=statement,
        supporting_evidence_ids=evidence_ids,
        confidence_score=confidence_score,
        topic_tags=topic_tags,
        is_untrusted=is_untrusted,
        is_quarantined=is_quarantined,
        metadata={"source_domain": source_domain},
    )


def test_analyst_protocol_compliance() -> None:
    """Test 12: Verify AnalystAgent satisfies AnalystProtocol."""
    agent = AnalystAgent()
    assert isinstance(agent, AnalystProtocol)


@pytest.mark.asyncio
async def test_valid_thematic_analysis() -> None:
    """Test 1: Verify valid thematic analysis creates cohesive, grounded KeyFindings."""
    agent = AnalystAgent()
    c1 = _make_claim(
        "Superconducting qubits operate at millikelvin temperatures.",
        ("ev_q1",),
        "c1",
        "run_q",
        confidence_score=0.95,
        topic_tags=("Quantum Computing",),
    )
    c2 = _make_claim(
        "Surface codes provide quantum error correction thresholds above 1 percent.",
        ("ev_q2",),
        "c2",
        "run_q",
        confidence_score=0.85,
        topic_tags=("Quantum Computing",),
    )

    result: ThematicAnalysisResult = await agent.analyze_claims(
        [c1, c2], run_id="run_q", research_goal="Quantum architectures"
    )

    assert result.run_id == "run_q"
    assert result.research_goal == "Quantum architectures"
    assert result.total_findings == 1
    assert result.claims_analyzed == 2
    assert result.evidence_ids_covered == ("ev_q1", "ev_q2")

    finding = result.findings[0]
    assert "Thematic Synthesis: Quantum Computing" in finding.title
    assert finding.run_id == "run_q"
    assert finding.claim_ids == ("c1", "c2")
    assert finding.evidence_ids == ("ev_q1", "ev_q2")
    assert finding.confidence_score == 0.90
    assert "Superconducting qubits" in finding.narrative
    assert "Surface codes" in finding.narrative


@pytest.mark.asyncio
async def test_empty_claims_rejection() -> None:
    """Test 2: Verify empty claim list is rejected with AnalysisError."""
    agent = AnalystAgent()
    with pytest.raises(AnalysisError) as exc_info:
        await agent.analyze_claims([], run_id="run_01")
    assert exc_info.value.code == "EMPTY_CLAIMS"


@pytest.mark.asyncio
async def test_invalid_empty_finding_rejection() -> None:
    """Test 3: Verify constructor rejects invalid max_findings or min_claims."""
    with pytest.raises(EvidenceValidationError):
        AnalystAgent(max_findings=0)
    with pytest.raises(EvidenceValidationError):
        AnalystAgent(min_claims_per_finding=-1)


@pytest.mark.asyncio
async def test_evidence_claim_provenance_preservation() -> None:
    """Test 4: Verify claim IDs and evidence IDs are accurately preserved in finding."""
    agent = AnalystAgent()
    c1 = _make_claim("Claim statement 1", ("ev_10", "ev_11"), "c_01", "run_p")
    c2 = _make_claim("Claim statement 2", ("ev_12",), "c_02", "run_p")

    res = await agent.analyze_claims([c1, c2], run_id="run_p")
    assert len(res.findings) == 1
    f = res.findings[0]
    assert set(f.claim_ids) == {"c_01", "c_02"}
    assert set(f.evidence_ids) == {"ev_10", "ev_11", "ev_12"}


@pytest.mark.asyncio
async def test_run_id_isolation() -> None:
    """Test 5: Verify analyzing claims with mismatched run_id raises EvidenceValidationError."""
    agent = AnalystAgent()
    c_a = _make_claim("Claim for run A", ("ev_a",), "c_a", "run_A")

    with pytest.raises(EvidenceValidationError) as exc_info:
        await agent.analyze_claims([c_a], run_id="run_B")
    assert "does not match analysis run_id" in str(exc_info.value)


@pytest.mark.asyncio
async def test_deterministic_clustering() -> None:
    """Test 6: Verify claims are clustered by topic_tags and produce distinct findings."""
    agent = AnalystAgent()
    c_ai_1 = _make_claim(
        "Transformer attention scales quadratically.",
        ("ev_ai1",),
        "c1",
        "run_ml",
        topic_tags=("AI",),
    )
    c_ai_2 = _make_claim(
        "Mixture-of-experts activates sparse sub-networks.",
        ("ev_ai2",),
        "c2",
        "run_ml",
        topic_tags=("AI",),
    )
    c_bio_1 = _make_claim(
        "CRISPR facilitates targeted RNA cleavage.",
        ("ev_bio1",),
        "c3",
        "run_ml",
        topic_tags=("Biotechnology",),
    )

    res = await agent.analyze_claims([c_ai_1, c_ai_2, c_bio_1], run_id="run_ml")
    assert res.total_findings == 2

    titles = [f.title for f in res.findings]
    assert "Thematic Synthesis: Ai" in titles
    assert "Thematic Synthesis: Biotechnology" in titles


@pytest.mark.asyncio
async def test_deterministic_ordering() -> None:
    """Test 7: Verify findings are ordered deterministically by confidence_score descending and title."""
    agent = AnalystAgent()
    c1 = _make_claim(
        "High confidence statement",
        ("ev_1",),
        "c1",
        "run_ord",
        confidence_score=0.95,
        topic_tags=("Alpha",),
    )
    c2 = _make_claim(
        "Medium confidence statement",
        ("ev_2",),
        "c2",
        "run_ord",
        confidence_score=0.75,
        topic_tags=("Beta",),
    )
    c3 = _make_claim(
        "Low confidence statement",
        ("ev_3",),
        "c3",
        "run_ord",
        confidence_score=0.50,
        topic_tags=("Gamma",),
    )

    res = await agent.analyze_claims([c3, c1, c2], run_id="run_ord")
    assert res.findings[0].title == "Thematic Synthesis: Alpha"
    assert res.findings[1].title == "Thematic Synthesis: Beta"
    assert res.findings[2].title == "Thematic Synthesis: Gamma"


@pytest.mark.asyncio
async def test_duplicate_claim_handling() -> None:
    """Test 8: Verify duplicate claims with identical claim_ids are deduplicated cleanly."""
    agent = AnalystAgent()
    c1 = _make_claim("Single statement", ("ev_1",), "c_dup", "run_dup")
    c1_copy = _make_claim("Single statement", ("ev_1",), "c_dup", "run_dup")

    res = await agent.analyze_claims([c1, c1_copy], run_id="run_dup")
    assert res.claims_analyzed == 1
    assert res.findings[0].claim_ids == ("c_dup",)


@pytest.mark.asyncio
async def test_untrusted_and_quarantined_provenance_handling() -> None:
    """Test 9: Verify KeyFinding inherits untrusted and quarantined flags if any claim is compromised."""
    agent = AnalystAgent()
    c_clean = _make_claim(
        "Clean proposition",
        ("ev_clean",),
        "c_clean",
        "run_sec",
        is_untrusted=False,
        is_quarantined=False,
        topic_tags=("Security",),
    )
    c_hostile = _make_claim(
        "Hostile injection",
        ("ev_sec",),
        "c_hostile",
        "run_sec",
        is_untrusted=True,
        is_quarantined=True,
        topic_tags=("Security",),
    )

    res = await agent.analyze_claims([c_clean, c_hostile], run_id="run_sec")
    assert res.total_findings == 1
    finding = res.findings[0]
    assert finding.is_untrusted is True
    assert finding.is_quarantined is True


def test_immutable_output_models() -> None:
    """Test 10: Verify KeyFinding and ThematicAnalysisResult are frozen/immutable."""
    finding = KeyFinding(
        finding_id="f1",
        title="Title",
        narrative="Narrative",
        claim_ids=("c1",),
        evidence_ids=("e1",),
    )
    with pytest.raises(ValidationError):
        finding.title = "Modified"

    res = ThematicAnalysisResult(
        run_id="run_01",
        findings=(finding,),
        claims_analyzed=1,
        evidence_ids_covered=("e1",),
        total_findings=1,
    )
    with pytest.raises(ValidationError):
        res.total_findings = 2


def test_extra_field_rejection() -> None:
    """Test 11: Verify extra fields are forbidden on KeyFinding and ThematicAnalysisResult."""
    with pytest.raises(ValidationError):
        KeyFinding(
            finding_id="f1",
            title="Title",
            narrative="Narrative",
            claim_ids=("c1",),
            evidence_ids=("e1",),
            unknown_field="injected",  # type: ignore[call-arg]
        )

    with pytest.raises(ValidationError):
        ThematicAnalysisResult(
            run_id="run_01",
            findings=(),
            claims_analyzed=0,
            evidence_ids_covered=(),
            total_findings=0,
            extra_payload="rejected",  # type: ignore[call-arg]
        )


@pytest.mark.asyncio
async def test_end_to_end_evidence_to_claim_to_analyst_pipeline() -> None:
    """Test 13: Full lifecycle test: EvidenceRecord -> DeterministicClaimExtractor -> AnalystAgent."""
    prov = SourceProvenance.from_content(
        raw_content="Deep neural networks require regularized gradient backpropagation to prevent exploding gradients.",
        title="Optimization in Deep Learning",
        source_url="https://nature.com/articles/dl-opt",
        trust_level=SourceTrustLevel.PEER_REVIEWED,
    )
    ev = EvidenceRecord.create(
        evidence_id="ev_dl_01",
        run_id="run_e2e",
        normalized_content="Deep neural networks require regularized gradient backpropagation to prevent exploding gradients.",
        provenance=prov,
    )

    extractor = DeterministicClaimExtractor()
    extracted = await extractor.extract_claims([ev], run_id="run_e2e")
    assert extracted.total_claims >= 1

    analyst = AnalystAgent()
    analysis_res = await analyst.analyze_claims(
        list(extracted.claims),
        run_id="run_e2e",
        research_goal="Deep learning optimization techniques",
    )

    assert analysis_res.total_findings >= 1
    f = analysis_res.findings[0]
    assert (
        "Optimization in Deep Learning" in f.narrative
        or "Deep neural networks" in f.narrative
    )
    assert "ev_dl_01" in f.evidence_ids
    assert f.run_id == "run_e2e"
    assert f.confidence_score == 0.95


def test_generate_finding_id_utility() -> None:
    """Verify generate_finding_id utility generates distinct prefixed IDs."""
    f1 = generate_finding_id()
    f2 = generate_finding_id()
    assert f1 != f2
    assert f1.startswith("fnd_")
