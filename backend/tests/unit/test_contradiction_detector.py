"""Comprehensive unit tests for Phase 3.4.3 ContradictionDetector and ContradictionItem Domain."""

import pytest
from pydantic import ValidationError

from app.common.enums import SourceTrustLevel
from app.common.errors import EvidenceValidationError
from app.intelligence.claims import (
    DeterministicClaimExtractor,
    ExtractedClaim,
)
from app.intelligence.contradiction import (
    ContradictionDetectionResult,
    ContradictionDetector,
    ContradictionDetectorProtocol,
    generate_contradiction_id,
)
from app.intelligence.evidence import EvidenceRecord, SourceProvenance
from app.intelligence.models import ContradictionItem


def _make_claim(
    statement: str,
    evidence_ids: tuple[str, ...] = ("ev_01",),
    claim_id: str = "clm_01",
    run_id: str = "run_01",
    confidence_score: float = 0.90,
    topic_tags: tuple[str, ...] = ("Economics",),
    is_untrusted: bool = False,
    is_quarantined: bool = False,
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
    )


def test_contradiction_detector_protocol_compliance() -> None:
    """Test 15: Verify ContradictionDetector satisfies ContradictionDetectorProtocol."""
    detector = ContradictionDetector()
    assert isinstance(detector, ContradictionDetectorProtocol)


@pytest.mark.asyncio
async def test_valid_contradiction_detection() -> None:
    """Test 1: Verify valid contradictory claims (e.g. increase vs decrease) are detected."""
    detector = ContradictionDetector()
    c1 = _make_claim(
        "Hybrid RAG reduces per-query compute cost by 68 percent.",
        ("ev_paper_a",),
        "c1",
        "run_cost",
        confidence_score=0.92,
        topic_tags=("RAG Economics",),
    )
    c2 = _make_claim(
        "Hybrid RAG increases per-query compute cost significantly.",
        ("ev_paper_b",),
        "c2",
        "run_cost",
        confidence_score=0.88,
        topic_tags=("RAG Economics",),
    )

    result: ContradictionDetectionResult = await detector.detect_contradictions(
        [c1, c2], run_id="run_cost"
    )

    assert result.run_id == "run_cost"
    assert result.has_contradictions is True
    assert result.total_contradictions == 1
    assert result.claims_evaluated == 2

    item = result.contradictions[0]
    assert item.conflicting_claim_ids == ("c1", "c2")
    assert item.conflicting_evidence_ids == ("ev_paper_a", "ev_paper_b")
    assert item.severity_score == 0.88
    assert "Opposing terms detected" in item.description


@pytest.mark.asyncio
async def test_valid_non_contradictory_claims() -> None:
    """Test 2: Verify complementary/non-contradictory claims produce zero contradictions."""
    detector = ContradictionDetector()
    c1 = _make_claim(
        "Transformers utilize self-attention mechanisms for sequence modeling.",
        ("ev_1",),
        "c1",
        "run_ai",
    )
    c2 = _make_claim(
        "Transformers scale efficiently across parallel GPU clusters.",
        ("ev_2",),
        "c2",
        "run_ai",
    )

    result = await detector.detect_contradictions([c1, c2], run_id="run_ai")
    assert result.has_contradictions is False
    assert result.total_contradictions == 0
    assert len(result.contradictions) == 0


@pytest.mark.asyncio
async def test_empty_input_handling() -> None:
    """Test 3: Verify empty claims list returns empty result gracefully."""
    detector = ContradictionDetector()
    result = await detector.detect_contradictions([], run_id="run_empty")
    assert result.has_contradictions is False
    assert result.total_contradictions == 0
    assert result.claims_evaluated == 0


@pytest.mark.asyncio
async def test_invalid_claim_rejection() -> None:
    """Test 4: Verify non-ExtractedClaim inputs or non-list inputs raise TypeError."""
    detector = ContradictionDetector()
    with pytest.raises(TypeError):
        await detector.detect_contradictions("invalid", run_id="run_01")  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        await detector.detect_contradictions([{"not": "claim"}], run_id="run_01")  # type: ignore[list-item]


@pytest.mark.asyncio
async def test_strict_run_id_isolation() -> None:
    """Test 5: Verify claims with mismatched run_id raise EvidenceValidationError."""
    detector = ContradictionDetector()
    c1 = _make_claim("Claim A", ("ev_1",), "c1", "run_A")
    c2 = _make_claim("Claim B", ("ev_2",), "c2", "run_B")

    with pytest.raises(EvidenceValidationError) as exc_info:
        await detector.detect_contradictions([c1, c2], run_id="run_A")
    assert "does not match contradiction detection run_id" in str(exc_info.value)


@pytest.mark.asyncio
async def test_self_comparison_prevention() -> None:
    """Test 6: Verify single claim is not compared against itself."""
    detector = ContradictionDetector()
    c1 = _make_claim(
        "Hybrid RAG reduces cost significantly.", ("ev_1",), "c1", "run_self"
    )

    result = await detector.detect_contradictions([c1], run_id="run_self")
    assert result.has_contradictions is False
    assert result.total_contradictions == 0


@pytest.mark.asyncio
async def test_duplicate_ab_ba_prevention() -> None:
    """Test 7: Verify A-B and B-A duplicate pairs produce only one canonical contradiction."""
    detector = ContradictionDetector()
    c1 = _make_claim(
        "Drug X is safe and non-toxic in clinical trials.",
        ("ev_1",),
        "c_drug_1",
        "run_drug",
        topic_tags=("Pharma",),
    )
    c2 = _make_claim(
        "Drug X is hazardous and toxic in animal models.",
        ("ev_2",),
        "c_drug_2",
        "run_drug",
        topic_tags=("Pharma",),
    )

    result = await detector.detect_contradictions([c1, c2], run_id="run_drug")
    assert result.total_contradictions == 1
    assert result.contradictions[0].conflicting_claim_ids == (
        "c_drug_1",
        "c_drug_2",
    )


@pytest.mark.asyncio
async def test_deterministic_contradiction_ids() -> None:
    """Test 8: Verify identical input claims produce identical deterministic contradiction IDs."""
    detector = ContradictionDetector()
    c1 = _make_claim("Model outperforms baselines.", ("ev_1",), "c1", "run_det")
    c2 = _make_claim("Model underperforms baselines.", ("ev_2",), "c2", "run_det")

    res1 = await detector.detect_contradictions([c1, c2], run_id="run_det")
    res2 = await detector.detect_contradictions([c2, c1], run_id="run_det")

    assert res1.contradictions[0].item_id == res2.contradictions[0].item_id


@pytest.mark.asyncio
async def test_deterministic_ordering() -> None:
    """Test 9: Verify contradictions are ordered by severity_score descending."""
    detector = ContradictionDetector()
    # High severity contradiction (confidence 0.95 and 0.90 -> severity 0.90)
    c_hi_1 = _make_claim(
        "System throughput increases under high load.",
        ("ev_h1",),
        "c_h1",
        "run_ord",
        confidence_score=0.95,
        topic_tags=("Perf",),
    )
    c_hi_2 = _make_claim(
        "System throughput decreases under high load.",
        ("ev_h2",),
        "c_h2",
        "run_ord",
        confidence_score=0.90,
        topic_tags=("Perf",),
    )

    # Low severity contradiction (confidence 0.50 and 0.40 -> severity 0.40)
    c_lo_1 = _make_claim(
        "Algorithm accuracy improves with smaller batch size.",
        ("ev_l1",),
        "c_l1",
        "run_ord",
        confidence_score=0.50,
        topic_tags=("Acc",),
    )
    c_lo_2 = _make_claim(
        "Algorithm accuracy degrades with smaller batch size.",
        ("ev_l2",),
        "c_l2",
        "run_ord",
        confidence_score=0.40,
        topic_tags=("Acc",),
    )

    res = await detector.detect_contradictions(
        [c_lo_1, c_lo_2, c_hi_1, c_hi_2], run_id="run_ord"
    )
    assert res.total_contradictions == 2
    assert res.contradictions[0].severity_score == 0.90
    assert res.contradictions[1].severity_score == 0.40


@pytest.mark.asyncio
async def test_claim_and_evidence_provenance_preservation() -> None:
    """Test 10 & 11: Verify claim IDs and evidence IDs are accurately preserved."""
    detector = ContradictionDetector()
    c1 = _make_claim(
        "Interconnect latency is lower in photonic networks.",
        ("ev_opt_01", "ev_opt_02"),
        "c1",
        "run_prov",
        topic_tags=("Optics",),
    )
    c2 = _make_claim(
        "Interconnect latency is higher in photonic networks.",
        ("ev_opt_03",),
        "c2",
        "run_prov",
        topic_tags=("Optics",),
    )

    res = await detector.detect_contradictions([c1, c2], run_id="run_prov")
    assert res.total_contradictions == 1
    item = res.contradictions[0]
    assert item.conflicting_claim_ids == ("c1", "c2")
    assert item.conflicting_evidence_ids == (
        "ev_opt_01",
        "ev_opt_02",
        "ev_opt_03",
    )


@pytest.mark.asyncio
async def test_untrusted_and_quarantined_flag_propagation() -> None:
    """Test 12: Verify ContradictionItem inherits untrusted/quarantined status from conflicting claims."""
    detector = ContradictionDetector()
    c_clean = _make_claim(
        "Vaccine candidate is effective across age cohorts.",
        ("ev_clean",),
        "c1",
        "run_flags",
        topic_tags=("Health",),
    )
    c_hostile = _make_claim(
        "Vaccine candidate is ineffective across age cohorts.",
        ("ev_sec",),
        "c2",
        "run_flags",
        is_untrusted=True,
        is_quarantined=True,
        topic_tags=("Health",),
    )

    res = await detector.detect_contradictions([c_clean, c_hostile], run_id="run_flags")
    assert res.total_contradictions == 1
    item = res.contradictions[0]
    assert item.is_untrusted is True
    assert item.is_quarantined is True


def test_immutable_output_models() -> None:
    """Test 13: Verify ContradictionItem and ContradictionDetectionResult are frozen/immutable."""
    item = ContradictionItem(
        item_id="cnt_01",
        description="Desc",
        conflicting_claim_ids=("c1", "c2"),
        divergence_analysis="Analysis",
    )
    with pytest.raises(ValidationError):
        item.description = "New description"

    res = ContradictionDetectionResult(
        run_id="run_01",
        contradictions=(item,),
        claims_evaluated=2,
        total_contradictions=1,
        has_contradictions=True,
    )
    with pytest.raises(ValidationError):
        res.total_contradictions = 5


def test_extra_field_rejection() -> None:
    """Test 14: Verify extra fields are forbidden on contradiction models."""
    with pytest.raises(ValidationError):
        ContradictionItem(
            item_id="cnt_01",
            description="Desc",
            conflicting_claim_ids=("c1", "c2"),
            divergence_analysis="Analysis",
            unauthorized_field="injected",  # type: ignore[call-arg]
        )


@pytest.mark.asyncio
async def test_end_to_end_evidence_to_claims_to_contradiction() -> None:
    """Test 17: Full lifecycle integration: EvidenceRecord -> DeterministicClaimExtractor -> ContradictionDetector."""
    ev1 = EvidenceRecord.create(
        evidence_id="ev_src1",
        run_id="run_e2e_cnt",
        normalized_content="Preliminary studies report room temperature superconductivity is viable.",
        provenance=SourceProvenance.from_content(
            raw_content="Preliminary studies report room temperature superconductivity is viable.",
            title="Superconductivity Lab Report 1",
            source_url="https://arxiv.org/abs/1",
            trust_level=SourceTrustLevel.PEER_REVIEWED,
        ),
    )
    ev2 = EvidenceRecord.create(
        evidence_id="ev_src2",
        run_id="run_e2e_cnt",
        normalized_content="Replication efforts confirm room temperature superconductivity is unviable.",
        provenance=SourceProvenance.from_content(
            raw_content="Replication efforts confirm room temperature superconductivity is unviable.",
            title="Superconductivity Lab Report 2",
            source_url="https://nature.com/articles/2",
            trust_level=SourceTrustLevel.PEER_REVIEWED,
        ),
    )

    extractor = DeterministicClaimExtractor()
    extracted = await extractor.extract_claims([ev1, ev2], run_id="run_e2e_cnt")
    assert extracted.total_claims == 2

    detector = ContradictionDetector()
    res = await detector.detect_contradictions(
        list(extracted.claims), run_id="run_e2e_cnt"
    )

    assert res.has_contradictions is True
    assert res.total_contradictions == 1
    assert set(res.contradictions[0].conflicting_evidence_ids) == {
        "ev_src1",
        "ev_src2",
    }


def test_generate_contradiction_id_utility() -> None:
    """Verify generate_contradiction_id creates distinct prefixed identifiers."""
    id1 = generate_contradiction_id()
    id2 = generate_contradiction_id()
    assert id1 != id2
    assert id1.startswith("cnt_")
