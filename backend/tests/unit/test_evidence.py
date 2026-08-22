"""Unit tests for Phase 3.3.1 Evidence Domain Models and Cryptographic Provenance."""

import pytest
from pydantic import ValidationError

from app.common.enums import SourceTrustLevel
from app.intelligence.evidence import (
    EvidenceRecord,
    SourceProvenance,
    compute_sha256_hash,
    generate_evidence_id,
    generate_source_id,
)


def _make_sample_provenance(
    raw_content: str = "Empirical benchmark confirms linear scaling across 100 nodes.",
    title: str = "Scalability in Distributed Systems",
    source_url: str | None = "https://arxiv.org/abs/2601.12345",
    trust_level: SourceTrustLevel = SourceTrustLevel.PEER_REVIEWED,
) -> SourceProvenance:
    return SourceProvenance.from_content(
        raw_content=raw_content,
        title=title,
        source_url=source_url,
        doi="10.1000/182",
        authors=("Dr. A. Smith", "Dr. B. Jones"),
        domain="arxiv.org",
        trust_level=trust_level,
        metadata={"peer_reviewed": True},
    )


def test_a_sha256_determinism() -> None:
    """Test A: SHA-256 hash generation is completely deterministic across identical payloads."""
    text = "Quantum error correction codes achieve fault tolerance threshold."
    hash_1 = compute_sha256_hash(text)
    hash_2 = compute_sha256_hash(text)

    assert hash_1 == hash_2
    assert len(hash_1) == 64
    assert hash_1.islower()
    assert all(c in "0123456789abcdef" for c in hash_1)


def test_b_sha256_changes_when_content_changes() -> None:
    """Test B: A single character change strictly alters the resulting SHA-256 hash."""
    base_text = "The quick brown fox jumps over the lazy dog"
    altered_text = "The quick brown fox jumps over the lazy dog."
    hash_base = compute_sha256_hash(base_text)
    hash_altered = compute_sha256_hash(altered_text)

    assert hash_base != hash_altered


def test_c_utf8_hashing_behavior() -> None:
    """Test C: UTF-8 multibyte characters and explicit byte arrays hash deterministically."""
    unicode_text = "Bioinformatics: CRISPR-Cas9 基因编辑 and α-helix proteins."
    hash_str = compute_sha256_hash(unicode_text)
    hash_bytes = compute_sha256_hash(unicode_text.encode("utf-8"))

    assert hash_str == hash_bytes


def test_d_evidence_id_distinct_from_content_hash() -> None:
    """Test D: evidence_id represents entity identity and MUST NOT equal content_hash."""
    content = "Factual research finding on distributed transactions."
    provenance = _make_sample_provenance(raw_content=content)
    record = EvidenceRecord.create(
        run_id="run_alpha_01",
        normalized_content=content,
        provenance=provenance,
    )

    assert record.evidence_id != record.content_hash
    assert record.evidence_id.startswith("ev_")
    assert len(record.content_hash) == 64

    # Direct rejection when evidence_id == content_hash
    with pytest.raises(ValidationError) as exc_info:
        EvidenceRecord(
            evidence_id=record.content_hash,  # Maliciously setting ID to hash
            run_id="run_alpha_01",
            provenance=provenance,
            content_hash=record.content_hash,
            normalized_content=content,
        )
    assert "evidence_id" in str(exc_info.value)
    assert "must not equal content_hash" in str(exc_info.value)


def test_e_evidence_records_are_immutable() -> None:
    """Test E: EvidenceRecord and SourceProvenance instances are frozen and immutable."""
    provenance = _make_sample_provenance()
    record = EvidenceRecord.create(
        run_id="run_01",
        normalized_content="Immutable evidence content.",
        provenance=provenance,
    )

    with pytest.raises(ValidationError):
        record.normalized_content = "Mutated content"

    with pytest.raises(ValidationError):
        provenance.title = "Mutated title"


def test_f_extra_attributes_are_rejected() -> None:
    """Test F: Extra or unapproved attributes are strictly rejected (extra='forbid')."""
    with pytest.raises(ValidationError):
        SourceProvenance(
            title="Title",
            content_hash="a" * 64,
            injected_field="malicious_payload",  # type: ignore[call-arg]
        )


def test_g_empty_content_rejected() -> None:
    """Test G: Empty or whitespace-only normalized content is rejected."""
    provenance = _make_sample_provenance()

    with pytest.raises(ValidationError):
        EvidenceRecord.create(
            run_id="run_01",
            normalized_content="",
            provenance=provenance,
        )

    with pytest.raises(ValidationError):
        EvidenceRecord.create(
            run_id="run_01",
            normalized_content="   \n\t  ",
            provenance=provenance,
        )


def test_h_missing_run_id_rejected() -> None:
    """Test H: Empty or missing run_id is strictly rejected."""
    provenance = _make_sample_provenance()

    with pytest.raises(ValidationError):
        EvidenceRecord.create(
            run_id="",
            normalized_content="Valid content.",
            provenance=provenance,
        )


def test_i_missing_provenance_rejected() -> None:
    """Test I: Constructing an EvidenceRecord without SourceProvenance raises ValidationError."""
    with pytest.raises(ValidationError):
        EvidenceRecord(  # type: ignore[call-arg]
            evidence_id="ev_001",
            run_id="run_01",
            content_hash="b" * 64,
            normalized_content="Valid content.",
        )


def test_j_valid_provenance_accepted() -> None:
    """Test J: Valid SourceProvenance fields, DOI, URL, authors are accepted cleanly."""
    provenance = SourceProvenance.from_content(
        raw_content="Raw academic paper text.",
        title="Journal of Deep Learning",
        source_url="https://doi.org/10.1016/j.neucom.2026.01.001",
        doi="10.1016/j.neucom.2026.01.001",
        publisher="Elsevier",
        authors=("Alice", "Bob"),
        domain="doi.org",
        trust_level=SourceTrustLevel.PEER_REVIEWED,
        metadata={"citation_count": 42},
    )
    assert provenance.source_id.startswith("src_")
    assert provenance.publisher == "Elsevier"
    assert provenance.doi == "10.1016/j.neucom.2026.01.001"
    assert len(provenance.authors) == 2


def test_k_serialization_and_deserialization_roundtrip() -> None:
    """Test K: EvidenceRecord cleanly serializes to JSON and deserializes without data loss."""
    content = "Microbiome diversity inversely correlates with inflammatory markers."
    provenance = _make_sample_provenance(raw_content=content)
    record = EvidenceRecord.create(
        run_id="run_bio_99",
        normalized_content=content,
        provenance=provenance,
        metadata={"sample_size": 1500, "p_value": 0.001},
        is_untrusted=False,
    )

    json_data = record.model_dump_json()
    reconstructed = EvidenceRecord.model_validate_json(json_data)

    assert reconstructed.evidence_id == record.evidence_id
    assert reconstructed.run_id == record.run_id
    assert reconstructed.content_hash == record.content_hash
    assert reconstructed.normalized_content == record.normalized_content
    assert reconstructed.provenance.title == record.provenance.title
    assert reconstructed.metadata == {"sample_size": 1500, "p_value": 0.001}


def test_l_metadata_preservation() -> None:
    """Test L: Arbitrary structured metadata dictionary is fully preserved."""
    meta = {"source_rank": 1, "tokens": 120, "tags": ["AI", "security"]}
    provenance = _make_sample_provenance()
    record = EvidenceRecord.create(
        run_id="run_01",
        normalized_content="Content with rich metadata.",
        provenance=provenance,
        metadata=meta,
    )
    assert record.metadata["source_rank"] == 1
    assert record.metadata["tags"] == ["AI", "security"]


def test_m_same_content_produces_same_content_hash() -> None:
    """Test M: Ingesting the same textual payload multiple times computes identical content_hash."""
    content = "Identical text content across multiple inquiries."
    prov_1 = SourceProvenance.from_content(raw_content=content, title="Title 1")
    prov_2 = SourceProvenance.from_content(raw_content=content, title="Title 2")

    assert prov_1.content_hash == prov_2.content_hash


def test_n_different_evidence_records_share_hash_without_sharing_id() -> None:
    """Test N: Two distinct evidence records can have the exact same content_hash while maintaining distinct evidence_ids."""
    content = "Universal law of gravitation holds across classical scales."
    prov = _make_sample_provenance(raw_content=content)

    rec_1 = EvidenceRecord.create(
        run_id="run_1", normalized_content=content, provenance=prov
    )
    rec_2 = EvidenceRecord.create(
        run_id="run_2", normalized_content=content, provenance=prov
    )

    # Identical content hash
    assert rec_1.content_hash == rec_2.content_hash
    # Distinct entity identities
    assert rec_1.evidence_id != rec_2.evidence_id
    assert rec_1.run_id == "run_1"
    assert rec_2.run_id == "run_2"


def test_o_run_id_remains_attached() -> None:
    """Test O: run_id remains explicitly attached to every EvidenceRecord."""
    provenance = _make_sample_provenance()
    record = EvidenceRecord.create(
        run_id="run_tenant_isolated_42",
        normalized_content="Isolated content.",
        provenance=provenance,
    )
    assert record.run_id == "run_tenant_isolated_42"


def test_id_generator_utilities() -> None:
    """Verify generate_evidence_id and generate_source_id produce unique prefixed identifiers."""
    id1 = generate_evidence_id()
    id2 = generate_evidence_id()
    src1 = generate_source_id()
    src2 = generate_source_id()

    assert id1 != id2
    assert id1.startswith("ev_")
    assert src1 != src2
    assert src1.startswith("src_")


def test_disallowed_url_scheme_rejected() -> None:
    """Verify dangerous URI schemes (e.g. javascript:, data:) are rejected in provenance."""
    with pytest.raises(ValidationError) as exc_info:
        SourceProvenance.from_content(
            raw_content="Payload",
            title="Dangerous Link",
            source_url="javascript:alert(1)",
        )
    assert "Disallowed URI scheme" in str(exc_info.value)
