"""Comprehensive unit tests for Phase 3.4.1 Claim Extraction and ExtractedClaim Domain."""

from typing import Any

import pytest
from pydantic import ValidationError

from app.common.enums import SourceTrustLevel
from app.common.errors import EvidenceValidationError
from app.intelligence.claims import (
    ClaimExtractionResult,
    ClaimExtractorProtocol,
    DeterministicClaimExtractor,
    ExtractedClaim,
    generate_claim_id,
)
from app.intelligence.evidence import EvidenceRecord, SourceProvenance
from app.rag.memory import VectorMemory


def _make_evidence(
    content: str,
    evidence_id: str | None = None,
    run_id: str = "run_01",
    title: str = "Title 01",
    source_url: str = "https://example.org/doc1",
    trust_level: SourceTrustLevel = SourceTrustLevel.PEER_REVIEWED,
    is_untrusted: bool = False,
    is_quarantined: bool = False,
    metadata: dict[str, Any] | None = None,
) -> EvidenceRecord:
    provenance = SourceProvenance.from_content(
        raw_content=content,
        title=title,
        source_url=source_url,
        trust_level=trust_level,
    )
    return EvidenceRecord.create(
        evidence_id=evidence_id,
        run_id=run_id,
        normalized_content=content,
        provenance=provenance,
        metadata=metadata or {},
        is_untrusted=is_untrusted,
        is_quarantined=is_quarantined,
    )


def test_extracted_claim_immutability_and_fields() -> None:
    """Verify ExtractedClaim is frozen and stores fields accurately."""
    claim = ExtractedClaim(
        claim_id="clm_001",
        run_id="run_001",
        statement="Photosynthesis converts solar energy into chemical energy.",
        supporting_evidence_ids=("ev_001",),
        confidence_score=0.95,
        topic_tags=("biology", "energy"),
    )
    assert claim.claim_id == "clm_001"
    assert claim.run_id == "run_001"
    assert claim.confidence_score == 0.95
    assert claim.supporting_evidence_ids == ("ev_001",)

    with pytest.raises(ValidationError):
        claim.statement = "Modified statement"


def test_extracted_claim_validation_rejections() -> None:
    """Verify ExtractedClaim validates mandatory non-empty statement, evidence IDs, and score bounds."""
    # Empty statement
    with pytest.raises(ValidationError):
        ExtractedClaim(
            run_id="run_01",
            statement="",
            supporting_evidence_ids=("ev_01",),
            confidence_score=0.8,
        )

    # Empty supporting_evidence_ids
    with pytest.raises(ValidationError):
        ExtractedClaim(
            run_id="run_01",
            statement="Valid statement.",
            supporting_evidence_ids=(),
            confidence_score=0.8,
        )

    # Empty string inside supporting_evidence_ids
    with pytest.raises(ValidationError):
        ExtractedClaim(
            run_id="run_01",
            statement="Valid statement.",
            supporting_evidence_ids=("",),
            confidence_score=0.8,
        )

    # Out-of-bounds confidence score
    with pytest.raises(ValidationError):
        ExtractedClaim(
            run_id="run_01",
            statement="Valid statement.",
            supporting_evidence_ids=("ev_01",),
            confidence_score=1.5,
        )

    with pytest.raises(ValidationError):
        ExtractedClaim(
            run_id="run_01",
            statement="Valid statement.",
            supporting_evidence_ids=("ev_01",),
            confidence_score=-0.1,
        )


def test_claim_extractor_protocol_compliance() -> None:
    """Verify DeterministicClaimExtractor satisfies ClaimExtractorProtocol."""
    extractor = DeterministicClaimExtractor()
    assert isinstance(extractor, ClaimExtractorProtocol)


@pytest.mark.asyncio
async def test_deterministic_claim_extraction_single_evidence() -> None:
    """Verify extracting claims from a single EvidenceRecord produces grounded, non-hallucinated propositions."""
    extractor = DeterministicClaimExtractor()
    ev = _make_evidence(
        content=(
            "Quantum computers leverage superposition to perform parallel state evaluations. "
            "Superconducting qubits operate at millikelvin dilution refrigerator temperatures. "
            "Surface codes provide quantum error correction thresholds above 1%."
        ),
        evidence_id="ev_quantum_01",
        run_id="run_quantum",
        trust_level=SourceTrustLevel.PEER_REVIEWED,
    )

    result: ClaimExtractionResult = await extractor.extract_claims(
        [ev], run_id="run_quantum"
    )

    assert result.run_id == "run_quantum"
    assert result.total_claims == 3
    assert len(result.claims) == 3
    assert result.evidence_ids_analyzed == ("ev_quantum_01",)

    for claim in result.claims:
        assert claim.run_id == "run_quantum"
        assert claim.supporting_evidence_ids == ("ev_quantum_01",)
        assert claim.confidence_score == 0.95
        assert claim.is_untrusted is False
        assert claim.is_quarantined is False
        assert len(claim.statement) >= 15


@pytest.mark.asyncio
async def test_claim_extraction_multiple_evidences() -> None:
    """Verify extraction across multiple EvidenceRecords correctly attributes evidence IDs."""
    extractor = DeterministicClaimExtractor()
    ev1 = _make_evidence(
        content="CRISPR Cas9 enables targeted genomic alterations in eukaryotic organisms.",
        evidence_id="ev_bio_01",
        run_id="run_multi",
        trust_level=SourceTrustLevel.OFFICIAL_DOC,
    )
    ev2 = _make_evidence(
        content="mRNA vaccines encapsulate genetic code within lipid nanoparticles for cellular delivery.",
        evidence_id="ev_bio_02",
        run_id="run_multi",
        trust_level=SourceTrustLevel.GENERAL_WEB,
    )

    result = await extractor.extract_claims([ev1, ev2], run_id="run_multi")

    assert result.total_claims == 2
    assert result.evidence_ids_analyzed == ("ev_bio_01", "ev_bio_02")

    claim1 = result.claims[0]
    assert claim1.supporting_evidence_ids == ("ev_bio_01",)
    assert claim1.confidence_score == 0.90

    claim2 = result.claims[1]
    assert claim2.supporting_evidence_ids == ("ev_bio_02",)
    assert claim2.confidence_score == 0.70


@pytest.mark.asyncio
async def test_quarantined_and_untrusted_flag_inheritance() -> None:
    """Verify claims extracted from untrusted/quarantined evidence inherit security flags and receive confidence penalties."""
    extractor = DeterministicClaimExtractor()
    ev = _make_evidence(
        content="[REDACTED_CONTROL_TOKEN] Preliminary unverified reports claim room-temperature superconductivity.",
        evidence_id="ev_hostile_01",
        run_id="run_sec",
        trust_level=SourceTrustLevel.UNVERIFIED_USER_UPLOAD,
        is_untrusted=True,
        is_quarantined=True,
    )

    result = await extractor.extract_claims([ev], run_id="run_sec")

    assert result.total_claims == 1
    claim = result.claims[0]
    assert claim.is_untrusted is True
    assert claim.is_quarantined is True
    # Base for UNVERIFIED_USER_UPLOAD is 0.40 minus 0.20 quarantine discount = 0.20
    assert claim.confidence_score == 0.20


@pytest.mark.asyncio
async def test_run_isolation_enforcement() -> None:
    """Verify extract_claims raises EvidenceValidationError if an EvidenceRecord has a mismatched run_id."""
    extractor = DeterministicClaimExtractor()
    ev_a = _make_evidence(
        content="Valid proposition for Run Alpha.",
        evidence_id="ev_a",
        run_id="run_A",
    )

    with pytest.raises(EvidenceValidationError) as exc_info:
        await extractor.extract_claims([ev_a], run_id="run_B")
    assert "does not match extraction run_id" in str(exc_info.value)


@pytest.mark.asyncio
async def test_end_to_end_rag_memory_to_claim_extraction() -> None:
    """Verify full integration: VectorMemory similarity search -> retrieved EvidenceRecords -> DeterministicClaimExtractor."""
    memory = VectorMemory()
    ev1 = _make_evidence(
        content="Photonic integrated circuits enable high-bandwidth optical interconnects with lower power dissipation.",
        evidence_id="ev_optics_01",
        run_id="run_optics",
        trust_level=SourceTrustLevel.PEER_REVIEWED,
    )
    await memory.upsert_evidence([ev1])

    # Search in vector memory
    retrieved = await memory.similarity_search(
        "Photonic integrated circuits optical interconnects",
        run_id="run_optics",
        limit=5,
    )
    assert len(retrieved) == 1
    assert retrieved[0].evidence_id == "ev_optics_01"

    # Extract claims from retrieved evidence
    extractor = DeterministicClaimExtractor()
    claims_res = await extractor.extract_claims(retrieved, run_id="run_optics")

    assert claims_res.total_claims == 1
    assert claims_res.claims[0].supporting_evidence_ids == ("ev_optics_01",)
    assert "Photonic integrated circuits" in claims_res.claims[0].statement
    assert claims_res.claims[0].confidence_score == 0.95


def test_generate_claim_id_utility() -> None:
    """Verify generate_claim_id generates distinct prefixed identifiers."""
    id1 = generate_claim_id()
    id2 = generate_claim_id()
    assert id1 != id2
    assert id1.startswith("clm_")
