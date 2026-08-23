"""Comprehensive unit tests for Phase 3.4.4 VerifierAgent, VerificationAudit, and Citation Mapping."""

import pytest
from pydantic import ValidationError

from app.common.enums import SourceTrustLevel, VerificationStatus
from app.common.errors import EvidenceValidationError
from app.intelligence.claims import (
    DeterministicClaimExtractor,
    ExtractedClaim,
)
from app.intelligence.evidence import EvidenceRecord, SourceProvenance
from app.intelligence.models import CitationReference, ContradictionItem
from app.intelligence.verifier import (
    VerificationResult,
    VerifierAgent,
    VerifierProtocol,
    generate_audit_id,
    generate_citation_key,
)


def _make_evidence(
    content: str,
    evidence_id: str = "ev_01",
    run_id: str = "run_01",
    title: str = "Source Title 01",
    source_url: str = "https://example.org/paper1",
    trust_level: SourceTrustLevel = SourceTrustLevel.PEER_REVIEWED,
    is_untrusted: bool = False,
    is_quarantined: bool = False,
) -> EvidenceRecord:
    prov = SourceProvenance.from_content(
        raw_content=content,
        title=title,
        source_url=source_url,
        trust_level=trust_level,
    )
    return EvidenceRecord.create(
        evidence_id=evidence_id,
        run_id=run_id,
        normalized_content=content,
        provenance=prov,
        is_untrusted=is_untrusted,
        is_quarantined=is_quarantined,
    )


def _make_claim(
    statement: str,
    evidence_ids: tuple[str, ...] = ("ev_01",),
    claim_id: str = "clm_01",
    run_id: str = "run_01",
    confidence_score: float = 0.90,
    is_untrusted: bool = False,
    is_quarantined: bool = False,
) -> ExtractedClaim:
    return ExtractedClaim(
        claim_id=claim_id,
        run_id=run_id,
        statement=statement,
        supporting_evidence_ids=evidence_ids,
        confidence_score=confidence_score,
        is_untrusted=is_untrusted,
        is_quarantined=is_quarantined,
    )


def test_verifier_protocol_compliance() -> None:
    """Test 11: Verify VerifierAgent satisfies VerifierProtocol."""
    agent = VerifierAgent()
    assert isinstance(agent, VerifierProtocol)


@pytest.mark.asyncio
async def test_valid_grounded_claim_verification() -> None:
    """Test 1: Verify fully grounded claim produces VERIFIED status and citations."""
    agent = VerifierAgent()
    ev1 = _make_evidence(
        "Superconducting quantum circuits operate below 20 millikelvin.",
        "ev_01",
        "run_q",
        title="Superconducting Qubits",
    )
    c1 = _make_claim(
        "Superconducting quantum circuits operate below 20 millikelvin.",
        ("ev_01",),
        "c1",
        "run_q",
        confidence_score=0.95,
    )

    result: VerificationResult = await agent.verify_claims([c1], [ev1], run_id="run_q")

    assert result.run_id == "run_q"
    assert result.overall_status == VerificationStatus.VERIFIED
    assert result.verified_count == 1
    assert result.unverified_count == 0
    assert result.contradicted_count == 0
    assert len(result.audits) == 1

    audit = result.audits[0]
    assert audit.claim_id == "c1"
    assert audit.status == VerificationStatus.VERIFIED
    assert audit.confidence_score == 0.95
    assert audit.verified_evidence_ids == ("ev_01",)

    assert len(result.citations) == 1
    cit = result.citations[0]
    assert cit.citation_key == "[CIT-01]"
    assert cit.evidence_id == "ev_01"
    assert cit.title == "Superconducting Qubits"
    assert result.claim_to_citation_map == {"c1": ("[CIT-01]",)}


@pytest.mark.asyncio
async def test_missing_ungrounded_evidence_rejection() -> None:
    """Test 2: Verify claim with missing evidence ID in evidence pool is marked UNVERIFIED."""
    agent = VerifierAgent()
    c1 = _make_claim(
        "Hallucinated claim statement.",
        ("ev_missing_999",),
        "c_unverified",
        "run_unv",
        confidence_score=0.90,
    )

    result = await agent.verify_claims([c1], [], run_id="run_unv")

    assert result.overall_status == VerificationStatus.UNVERIFIED
    assert result.verified_count == 0
    assert result.unverified_count == 1
    assert len(result.citations) == 0

    audit = result.audits[0]
    assert audit.status == VerificationStatus.UNVERIFIED
    assert audit.confidence_score == 0.0
    assert "not found in the verified evidence pool" in audit.reasoning


@pytest.mark.asyncio
async def test_contradicted_claim_verification() -> None:
    """Test 3: Verify claim listed in ContradictionItem is marked CONTRADICTED with refuting evidence."""
    agent = VerifierAgent()
    ev1 = _make_evidence("Drug A reduces hypertension.", "ev_01", "run_cnt")
    ev2 = _make_evidence("Drug A increases hypertension.", "ev_02", "run_cnt")

    c1 = _make_claim("Drug A reduces hypertension.", ("ev_01",), "c1", "run_cnt")
    c2 = _make_claim("Drug A increases hypertension.", ("ev_02",), "c2", "run_cnt")

    contradiction = ContradictionItem(
        item_id="cnt_01",
        run_id="run_cnt",
        description="Divergence on Drug A effect",
        conflicting_claim_ids=("c1", "c2"),
        conflicting_evidence_ids=("ev_01", "ev_02"),
        divergence_analysis="Competing clinical findings",
        severity_score=0.90,
    )

    result = await agent.verify_claims(
        [c1, c2], [ev1, ev2], run_id="run_cnt", contradictions=[contradiction]
    )

    assert result.overall_status == VerificationStatus.CONTRADICTED
    assert result.contradicted_count == 2
    assert result.verified_count == 0

    audit1 = result.audits[0]
    assert audit1.status == VerificationStatus.CONTRADICTED
    assert set(audit1.refuting_evidence_ids) == {"ev_01", "ev_02"}
    assert "directly disputed" in audit1.reasoning


@pytest.mark.asyncio
async def test_empty_claims_handling() -> None:
    """Test 4: Verify empty claims list returns empty VerificationResult cleanly."""
    agent = VerifierAgent()
    res = await agent.verify_claims([], [], run_id="run_empty")
    assert res.overall_status == VerificationStatus.UNVERIFIED
    assert res.verified_count == 0
    assert res.average_confidence == 0.0


@pytest.mark.asyncio
async def test_strict_run_id_isolation() -> None:
    """Test 5: Verify claims or evidence from other runs raise EvidenceValidationError."""
    agent = VerifierAgent()
    ev_a = _make_evidence("Evidence Run A", "ev_a", run_id="run_A")
    ev_b = _make_evidence("Evidence Run B", "ev_b", run_id="run_B")
    c_a = _make_claim("Claim Run A", ("ev_a",), "c_a", run_id="run_A")

    # Mismatched evidence run_id
    with pytest.raises(EvidenceValidationError) as exc_info:
        await agent.verify_claims([c_a], [ev_a, ev_b], run_id="run_A")
    assert "does not match verification run_id" in str(exc_info.value)

    # Mismatched claim run_id
    with pytest.raises(EvidenceValidationError) as exc_info:
        await agent.verify_claims([c_a], [ev_a], run_id="run_B")
    assert "does not match verification run_id" in str(exc_info.value)


@pytest.mark.asyncio
async def test_deterministic_citation_generation() -> None:
    """Test 6: Verify citations are generated sequentially in deterministic sorted order."""
    agent = VerifierAgent()
    ev_b = _make_evidence("Beta evidence", "ev_b", "run_cit", title="Beta Title")
    ev_a = _make_evidence("Alpha evidence", "ev_a", "run_cit", title="Alpha Title")

    c1 = _make_claim("Alpha and Beta claim", ("ev_b", "ev_a"), "c1", "run_cit")

    res = await agent.verify_claims([c1], [ev_b, ev_a], run_id="run_cit")

    assert len(res.citations) == 2
    assert res.citations[0].citation_key == "[CIT-01]"
    assert res.citations[0].evidence_id == "ev_a"
    assert res.citations[1].citation_key == "[CIT-02]"
    assert res.citations[1].evidence_id == "ev_b"
    assert res.claim_to_citation_map["c1"] == ("[CIT-01]", "[CIT-02]")


@pytest.mark.asyncio
async def test_deterministic_audit_ids() -> None:
    """Test 7: Verify identical claim verification produces identical deterministic audit IDs."""
    agent = VerifierAgent()
    ev1 = _make_evidence("Content", "ev_01", "run_det")
    c1 = _make_claim("Content", ("ev_01",), "c1", "run_det")

    res1 = await agent.verify_claims([c1], [ev1], run_id="run_det")
    res2 = await agent.verify_claims([c1], [ev1], run_id="run_det")

    assert res1.audits[0].audit_id == res2.audits[0].audit_id


@pytest.mark.asyncio
async def test_untrusted_and_quarantined_flag_propagation() -> None:
    """Test 8: Verify CitationReference inherits untrusted/quarantined status and confidence is discounted."""
    agent = VerifierAgent()
    ev_hostile = _make_evidence(
        "Hostile payload text",
        "ev_sec",
        "run_sec",
        is_untrusted=True,
        is_quarantined=True,
    )
    c_sec = _make_claim(
        "Hostile payload text",
        ("ev_sec",),
        "c_sec",
        "run_sec",
        confidence_score=0.80,
        is_untrusted=True,
        is_quarantined=True,
    )

    res = await agent.verify_claims([c_sec], [ev_hostile], run_id="run_sec")

    assert res.verified_count == 1
    cit = res.citations[0]
    assert cit.is_untrusted is True
    assert cit.is_quarantined is True
    # 0.80 * 0.90 = 0.72
    assert res.audits[0].confidence_score == 0.72


def test_immutable_models_and_extra_field_rejection() -> None:
    """Test 9 & 10: Verify models are frozen and reject extra fields."""
    cit = CitationReference(
        citation_key="[CIT-01]",
        evidence_id="ev_01",
        source_url="https://example.org",
        title="Title",
        domain="example.org",
    )
    with pytest.raises(ValidationError):
        cit.title = "Modified"

    with pytest.raises(ValidationError):
        CitationReference(
            citation_key="[CIT-01]",
            evidence_id="ev_01",
            source_url="https://example.org",
            title="Title",
            domain="example.org",
            illegal_injected_param="forbidden",  # type: ignore[call-arg]
        )


@pytest.mark.asyncio
async def test_end_to_end_evidence_to_claim_to_verification() -> None:
    """Test 12: Full lifecycle test: EvidenceRecord -> DeterministicClaimExtractor -> VerifierAgent."""
    ev = EvidenceRecord.create(
        evidence_id="ev_e2e_01",
        run_id="run_full_e2e",
        normalized_content="CRISPR Cas9 enables precise genomic sequence alterations.",
        provenance=SourceProvenance.from_content(
            raw_content="CRISPR Cas9 enables precise genomic sequence alterations.",
            title="CRISPR Genomic Editing",
            source_url="https://nature.com/articles/crispr",
            trust_level=SourceTrustLevel.PEER_REVIEWED,
        ),
    )

    extractor = DeterministicClaimExtractor()
    extracted = await extractor.extract_claims([ev], run_id="run_full_e2e")
    assert extracted.total_claims >= 1

    verifier = VerifierAgent()
    ver_res = await verifier.verify_claims(
        list(extracted.claims), [ev], run_id="run_full_e2e"
    )

    assert ver_res.overall_status == VerificationStatus.VERIFIED
    assert ver_res.verified_count == extracted.total_claims
    assert len(ver_res.citations) == 1
    assert ver_res.citations[0].title == "CRISPR Genomic Editing"


def test_generate_audit_id_and_citation_key_utilities() -> None:
    """Verify generate_audit_id and generate_citation_key utilities."""
    a1 = generate_audit_id()
    a2 = generate_audit_id()
    assert a1 != a2
    assert a1.startswith("aud_")

    k1 = generate_citation_key(1)
    k99 = generate_citation_key(99)
    assert k1 == "[CIT-01]"
    assert k99 == "[CIT-99]"
