"""Unit tests for evidence, provenance, and verification audit models."""

import pytest
from pydantic import ValidationError

from app.common.enums import SourceTrustLevel, VerificationStatus
from app.common.evidence import (
    EvidenceRecord,
    ExtractedClaim,
    SourceProvenance,
    VerificationAudit,
)


def test_source_provenance_hash_computation() -> None:
    """Verify cryptographic content hash calculation and provenance modeling."""
    raw_html = "<html><body>Empirical evaluation of deep agents</body></html>"
    content_hash = SourceProvenance.compute_content_hash(raw_html)

    prov = SourceProvenance(
        source_url="https://arxiv.org/abs/2401.00001",
        title="Empirical Evaluation of Deep Agents",
        authors=("Alice Smith", "Bob Jones"),
        domain="arxiv.org",
        trust_level=SourceTrustLevel.PEER_REVIEWED,
        content_hash=content_hash,
    )
    assert prov.domain == "arxiv.org"
    assert prov.trust_level == SourceTrustLevel.PEER_REVIEWED
    assert len(prov.content_hash) == 64


def test_evidence_record_validation() -> None:
    """Verify EvidenceRecord bounds and properties."""
    prov = SourceProvenance(
        source_url="https://example.com/data",
        title="Example Data",
        domain="example.com",
        content_hash=SourceProvenance.compute_content_hash("data"),
    )

    record = EvidenceRecord(
        evidence_id="ev_01",
        run_id="run_100",
        subtask_id="task_01",
        provenance=prov,
        extracted_quote="The model achieves 94.2% accuracy on benchmark X.",
        context_summary="Section 4.1 Results Table",
        relevance_score=0.95,
        is_untrusted=True,
    )
    assert record.relevance_score == 0.95
    assert record.is_untrusted is True

    # Validate relevance_score bounds
    with pytest.raises(ValidationError):
        EvidenceRecord(
            evidence_id="ev_02",
            run_id="run_100",
            subtask_id="task_01",
            provenance=prov,
            extracted_quote="Invalid score test",
            context_summary="Context",
            relevance_score=1.5,  # > 1.0 invalid
        )


def test_extracted_claim_requires_supporting_evidence() -> None:
    """Verify an ExtractedClaim cannot have empty supporting_evidence_ids."""
    with pytest.raises(ValidationError):
        ExtractedClaim(
            claim_id="cl_01",
            run_id="run_100",
            statement="Ungrounded claim with no evidence",
            supporting_evidence_ids=(),  # Empty tuple rejected
            confidence_score=0.8,
        )


def test_extracted_claim_valid_traceability() -> None:
    """Verify valid ExtractedClaim creation with evidence references."""
    claim = ExtractedClaim(
        claim_id="cl_01",
        run_id="run_100",
        statement="Asynchronous execution scales linearly with worker count.",
        supporting_evidence_ids=("ev_01", "ev_02"),
        confidence_score=0.92,
        contradiction_notes="Paper B reports saturation after 16 workers.",
    )
    assert claim.claim_id == "cl_01"
    assert len(claim.supporting_evidence_ids) == 2
    assert claim.confidence_score == 0.92


def test_verification_audit_record() -> None:
    """Verify VerificationAudit record attributes and structure."""
    audit = VerificationAudit(
        audit_id="aud_01",
        claim_id="cl_01",
        run_id="run_100",
        status=VerificationStatus.PARTIALLY_VERIFIED,
        confidence_score=0.78,
        verified_evidence_ids=("ev_01",),
        refuting_evidence_ids=("ev_03",),
        reasoning="Strong empirical evidence up to 16 workers, but conflicting evidence beyond.",
        auditor_agent_role="verifier",
    )
    assert audit.status == VerificationStatus.PARTIALLY_VERIFIED
    assert len(audit.verified_evidence_ids) == 1
    assert len(audit.refuting_evidence_ids) == 1
    assert "conflicting evidence" in audit.reasoning
